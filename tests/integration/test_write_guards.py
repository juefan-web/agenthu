"""P0-3 slice 3: write guards — suppression, generation, barriers, §2.4.

Covers the A-draft §2.3 wiring surface end to end: upstream-anchor
suppression keeps a deleted source from resurrecting under a fresh
client_event_id (single + batch), X-Data-Generation entry checks on the
sync batch path, scoped barriers failing closed on chat/memory writes,
§2.4 terminal states for runs/actions cut down by a deletion, the
projection skip under an account barrier, the durable orphan ledger that
replaces the destructive Redis SPOP, the account closure now ending
suppression rows, and the E7-3 "transient edits die with the anchored
derivation" behavior.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import redis as redis_lib
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.adapters.model_provider.base import EmbeddingResult, ModelTurn
from backend.config import get_settings
from backend.models.agent import AgentRun, PendingAction
from backend.models.chat import ChatMessage
from backend.models.data_lifecycle import (
    DataCleanupItem,
    DataOperation,
    DataReceipt,
    DataSuppression,
    StorageOrphanKey,
)
from backend.models.enums import DataBarrierScope
from backend.models.event import Event
from backend.models.file import FileObject
from backend.models.material import GroundingConsent, MaterialChunk
from backend.models.memory import Memory
from backend.models.task import Task
from backend.schemas.client_contract import EventEnvelope, EventProvenance
from backend.schemas.event import EventCreate
from backend.services import data_lifecycle as dl
from backend.services import data_operations as ops
from backend.services.agent_runner import dispatch_confirmed_action, execute_run
from backend.services.current_state import (
    flush_state_recompute,
    get_or_create_state,
    mark_state_dirty,
)
from backend.services.data_executor import run_deletion
from backend.services.events import (
    DEDUPE_TOO_LONG_REASON,
    create_event,
    ingest_event_batch,
)
from backend.services.material_ingestion import embed_pending_chunks, run_extraction
from backend.services.storage_orphans import (
    claim_due_storage_orphans,
    fail_storage_orphan,
    register_storage_orphan,
    release_storage_orphan,
)
from backend.services.write_guards import (
    SUPPRESSED_REASON,
    SuppressedSource,
    release_source_suppressions,
)

pytestmark = pytest.mark.integration


class FakeToolProvider:
    """Scripted provider (same shape as the M4 runtime tests)."""

    name = "fake"
    model_name = "fake-model"

    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)
        self.calls = 0

    def capabilities(self):  # pragma: no cover - unused in these tests
        from backend.adapters.model_provider.base import ProviderCapabilities

        return ProviderCapabilities(text_generation=True, tool_calls=True)

    async def generate_with_tools(self, input_text, instructions, tool_schemas):
        self.calls += 1
        return self.turns.pop(0)

    async def continue_with_tool_results(self, turn, results):  # pragma: no cover
        self.calls += 1
        return self.turns.pop(0)

    async def generate(self, input_text, instructions=None):  # pragma: no cover
        return "fake"

    def build_responses_request(self, model, input_text, instructions=None):  # pragma: no cover
        return {"model": model, "input": input_text}


class _session_ctx:
    """drain_storage_orphans's session_scope stand-in bound to the test
    session (the worker's own sessionmaker would open a second connection
    outside the fixture's outer transaction)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


def _me(client, headers) -> uuid.UUID:
    return uuid.UUID(client.get("/v1/auth/me", headers=headers).json()["id"])


def _anchor_event_payload(
    *, upstream_id: str, event_type: str = "study.assignment.created", explicit_dedupe: bool = True
):
    # explicit_dedupe=False omits the key so the backend computes it from
    # (source, upstream_id, semantic_version); used where seed and replay
    # must share one dedupe key (the ordering pin below).
    return EventCreate(
        type=event_type,
        source="onethu",
        timestamp=datetime.now(UTC),
        data={"title": f"HW {upstream_id}", "course": "Linear Algebra"},
        context={"origin": "write-guard-test"},
        provenance={
            "connector": "onethu",
            "connector_version": "1",
            "upstream_id": upstream_id,
            "semantic_version": "1",
            "fetched_at": datetime.now(UTC).isoformat(),
        },
        dedupe_key=f"t:{uuid.uuid4().hex}" if explicit_dedupe else None,
    )


def _anchor_envelope(*, upstream_id: str, client_event_id: str) -> EventEnvelope:
    payload = _anchor_event_payload(upstream_id=upstream_id)
    return EventEnvelope(
        client_event_id=client_event_id,
        type=payload.type,
        occurred_at=payload.timestamp,
        source=payload.source,
        data=payload.data,
        context=payload.context,
        provenance=EventProvenance.model_validate(payload.provenance),
    )


def _seed_anchor_event(
    client,
    headers,
    *,
    upstream_id: str,
    event_type: str | None = None,
    explicit_dedupe: bool = True,
) -> str:
    payload = _anchor_event_payload(
        upstream_id=upstream_id,
        event_type=event_type or "study.assignment.created",
        explicit_dedupe=explicit_dedupe,
    )
    response = client.post("/v1/events", json=payload.model_dump(mode="json"), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _preview(client, headers, target: dict) -> dict:
    response = client.post("/v1/data/previews", json=target, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _confirm(client, headers, preview: dict, *, key: str) -> dict:
    response = client.post(
        "/v1/data/deletions",
        json={
            "preview_id": preview["id"],
            "preview_digest": preview["preview_digest"],
            "client_request_id": key,
            "confirmed": True,
        },
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return response.json()


def _confirm_source_event(client, headers, event_id: str, *, key: str) -> dict:
    preview = _preview(
        client, headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
    )
    return _confirm(client, headers, preview, key=key)


def _seed_memory_row(db_session: Session, user_id) -> Memory:
    memory = Memory(
        user_id=user_id, level=1, domain="study", content="episode content", confidence=0.6
    )
    db_session.add(memory)
    db_session.flush()
    return memory


# ------------------------------------------------------------- suppression --


class TestSuppressionInterception:
    def test_deleted_anchor_reimport_blocked_across_client_event_ids(
        self, client, auth_headers, db_session
    ):
        user_id = _me(client, auth_headers)
        event_id = _seed_anchor_event(client, auth_headers, upstream_id="assignment:hw-9")
        _confirm_source_event(client, auth_headers, event_id, key="suppress-1")

        # Same (source, upstream_id) anchor under a brand-new event identity
        # is refused on the single path…
        replay = _anchor_event_payload(upstream_id="assignment:hw-9")
        response = client.post(
            "/v1/events", json=replay.model_dump(mode="json"), headers=auth_headers
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "source_deleted"

        # …and lands in the batch's per-envelope rejections, not a 409 that
        # would poison the rest of the queue.
        outcome = ingest_event_batch(
            db_session,
            user_id=user_id,
            envelopes=[_anchor_envelope(upstream_id="assignment:hw-9", client_event_id="c-1")],
        )
        assert outcome.rejected == [("c-1", SUPPRESSED_REASON)]
        assert outcome.accepted == []

    def test_overlong_dedupe_key_rejects_one_envelope_not_the_batch(
        self, client, auth_headers, db_session
    ):
        """External review #9 pin: an unbounded provenance.upstream_id makes
        the computed dedupe key overflow String(255); the INSERT used to
        roll back the WHOLE batch into a 500. The check sits in the
        per-envelope rejection chain — same level as suppression — and the
        good envelope in the same batch still lands."""

        me = client.get("/v1/auth/me", headers=auth_headers).json()
        user_id = uuid.UUID(me["id"])

        outcome = ingest_event_batch(
            db_session,
            user_id=user_id,
            envelopes=[
                _anchor_envelope(upstream_id="u" * 300, client_event_id="too-long-1"),
                _anchor_envelope(upstream_id="assignment:hw-42", client_event_id="good-1"),
            ],
        )

        assert outcome.rejected == [("too-long-1", DEDUPE_TOO_LONG_REASON)]
        assert outcome.accepted == ["good-1"]
        assert outcome.duplicates == []

        # A different anchor from the same source is unaffected — the guard
        # is anchor-scoped, not source-string-scoped.
        assert _seed_anchor_event(client, auth_headers, upstream_id="assignment:hw-10")

    def test_suppression_precedes_dedupe_in_barrier_window(self, client, auth_headers):
        # Ordering pin (review checkpoint 3): seed and replay carry no
        # explicit dedupe_key, so both share the backend-computed key from
        # (source, upstream_id, semantic_version). The pre-barrier replay
        # proves that key hits the dedupe lookup (200 + X-Deduplicated);
        # after confirm — rows not yet reaped — the identical payload must
        # 409 instead of silently returning the doomed row.
        upstream_id = "assignment:hw-d"
        event_id = _seed_anchor_event(
            client, auth_headers, upstream_id=upstream_id, explicit_dedupe=False
        )

        replay = _anchor_event_payload(upstream_id=upstream_id, explicit_dedupe=False)
        pre_barrier = client.post(
            "/v1/events", json=replay.model_dump(mode="json"), headers=auth_headers
        )
        assert pre_barrier.status_code == 200, pre_barrier.text
        assert pre_barrier.headers["X-Deduplicated"] == "true"
        assert pre_barrier.json()["id"] == event_id

        _confirm_source_event(client, auth_headers, event_id, key="suppress-d")
        post_confirm = client.post(
            "/v1/events", json=replay.model_dump(mode="json"), headers=auth_headers
        )
        assert post_confirm.status_code == 409, post_confirm.text
        assert post_confirm.json()["error"]["code"] == "source_deleted"

    def test_release_after_reauthorization_reopens_the_anchor(
        self, client, auth_headers, db_session
    ):
        user_id = _me(client, auth_headers)
        event_id = _seed_anchor_event(client, auth_headers, upstream_id="assignment:hw-r")
        _confirm_source_event(client, auth_headers, event_id, key="suppress-r")

        released = release_source_suppressions(
            db_session, user_id=user_id, source_kind="event", upstream_ids=["assignment:hw-r"]
        )
        assert released == 1
        # Idempotent: the anchor is released, a second call is a no-op.
        assert (
            release_source_suppressions(
                db_session, user_id=user_id, source_kind="event", upstream_ids=["assignment:hw-r"]
            )
            == 0
        )

        payload = _anchor_event_payload(upstream_id="assignment:hw-r")
        response = client.post(
            "/v1/events", json=payload.model_dump(mode="json"), headers=auth_headers
        )
        assert response.status_code == 201, response.text

    def test_events_without_upstream_anchor_pass(self, client, auth_headers):
        _me(client, auth_headers)
        event_id = _seed_anchor_event(client, auth_headers, upstream_id="assignment:hw-n")
        _confirm_source_event(client, auth_headers, event_id, key="suppress-n")

        # Manual events carry no provenance.upstream_id: nothing to match —
        # the connector-side upstream_id precondition is a task-doc
        # discipline, not enforced at this boundary.
        payload = EventCreate(
            type="note.added",
            source="manual",
            timestamp=datetime.now(UTC),
            data={"text": "hello"},
            context={},
            provenance={"origin": "user"},
            dedupe_key=f"m:{uuid.uuid4().hex}",
        )
        response = client.post(
            "/v1/events", json=payload.model_dump(mode="json"), headers=auth_headers
        )
        assert response.status_code == 201, response.text

    def test_service_layer_raises_suppressed_source(self, client, auth_headers, db_session):
        user_id = _me(client, auth_headers)
        event_id = _seed_anchor_event(client, auth_headers, upstream_id="assignment:hw-s")
        _confirm_source_event(client, auth_headers, event_id, key="suppress-s")
        with pytest.raises(SuppressedSource):
            create_event(
                db_session,
                user_id=user_id,
                payload=_anchor_event_payload(upstream_id="assignment:hw-s"),
            )


# ----------------------------------------------------------- events entry --


class TestEventsEntryBarrier:
    """The A-draft §2.3 events leg (external review reconciliation): the
    account barrier fences event creation at the sink; scoped source/memory
    barriers do not, because a brand-new row names no id they hold."""

    def test_account_barrier_blocks_single_event_post(self, client, auth_headers, db_session):
        user_id = _me(client, auth_headers)
        handle = dl.owner_handle_of(db_session, user_id)
        dl.raise_barrier(
            db_session,
            owner_handle=handle,
            scope=DataBarrierScope.ACCOUNT,
            raised_generation=dl.bump_data_generation(db_session, user_id),
        )

        blocked = client.post(
            "/v1/events",
            json=_anchor_event_payload(upstream_id="assignment:hw-fenced").model_dump(mode="json"),
            headers=auth_headers,
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error"]["code"] == "deletion_in_progress"

    def test_account_barrier_rejects_every_batch_envelope(self, client, auth_headers, db_session):
        user_id = _me(client, auth_headers)
        handle = dl.owner_handle_of(db_session, user_id)
        dl.raise_barrier(
            db_session,
            owner_handle=handle,
            scope=DataBarrierScope.ACCOUNT,
            raised_generation=dl.bump_data_generation(db_session, user_id),
        )

        outcome = ingest_event_batch(
            db_session,
            user_id=user_id,
            envelopes=[
                _anchor_envelope(upstream_id="assignment:hw-b1", client_event_id="b-1"),
                _anchor_envelope(upstream_id="assignment:hw-b2", client_event_id="b-2"),
            ],
        )
        # Nothing was written, so each envelope rejects on its own — the
        # client clears them from the queue like any other rejected item.
        assert outcome.accepted == []
        assert outcome.duplicates == []
        assert [client_event_id for client_event_id, _ in outcome.rejected] == ["b-1", "b-2"]
        for _, reason in outcome.rejected:
            assert "deletion blocks this write" in reason

    def test_source_barrier_does_not_fence_new_events(self, client, auth_headers):
        # Scoped barriers hold event-row ids of the dying closure; a new
        # row cannot be one of them, so an unrelated event still lands
        # (re-imports of the deleted anchor stay the suppression net's job).
        _me(client, auth_headers)
        event_id = _seed_anchor_event(client, auth_headers, upstream_id="assignment:hw-src")
        _confirm_source_event(client, auth_headers, event_id, key="evt-bar-1")

        fresh = client.post(
            "/v1/events",
            json=_anchor_event_payload(upstream_id="assignment:hw-unrelated").model_dump(
                mode="json"
            ),
            headers=auth_headers,
        )
        assert fresh.status_code == 201, fresh.text


# ------------------------------------------------------------- generation --


class TestGenerationEntryCheck:
    def test_batch_stale_generation_409_with_live_header(self, client, auth_headers, db_session):
        user_id = _me(client, auth_headers)
        body = {
            "events": [
                json.loads(
                    _anchor_envelope(
                        upstream_id="assignment:hw-g", client_event_id="g-1"
                    ).model_dump_json()
                )
            ],
            "client_cursor": "cursor-1",
        }

        # Legacy compat: no header, no rejection — and never auto-filled.
        first = client.post("/v1/events/batch", json=body, headers=auth_headers)
        assert first.status_code == 200, first.text
        assert "X-Data-Generation" in first.headers
        live = int(first.headers["X-Data-Generation"])

        matching = client.post(
            "/v1/events/batch", json=body, headers={**auth_headers, "X-Data-Generation": str(live)}
        )
        assert matching.status_code == 200, matching.text

        # A real destructive confirm moves the generation; a queued view
        # pinned to the old one must re-base instead of mixing deleted
        # items into new batches.
        event_id = _seed_anchor_event(client, auth_headers, upstream_id="assignment:hw-g")
        _confirm_source_event(client, auth_headers, event_id, key="generation-1")
        stale = client.post(
            "/v1/events/batch",
            json={
                "events": [
                    json.loads(
                        _anchor_envelope(
                            upstream_id="assignment:hw-g2", client_event_id="g-2"
                        ).model_dump_json()
                    )
                ]
            },
            headers={**auth_headers, "X-Data-Generation": str(live)},
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["error"]["code"] == "generation_stale"
        assert int(stale.headers["X-Data-Generation"]) == live + 1
        assert ops.current_generation(db_session, user_id) == live + 1


# ---------------------------------------------------------------- barriers --


class TestScopedBarrierWrites:
    def test_message_into_session_under_deletion_409(self, client, auth_headers):
        _me(client, auth_headers)
        session = client.post("/v1/chat/sessions", json={"title": None}, headers=auth_headers)
        assert session.status_code == 201, session.text
        session_id = session.json()["id"]
        preview = _preview(
            client,
            auth_headers,
            {"kind": "source", "source_kind": "chat_session", "ids": [session_id]},
        )
        _confirm(client, auth_headers, preview, key="chat-bar-1")

        blocked = client.post(
            f"/v1/chat/sessions/{session_id}/messages",
            json={"content": "into the dying session", "client_message_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error"]["code"] == "deletion_in_progress"

        other = client.post("/v1/chat/sessions", json={"title": None}, headers=auth_headers)
        ok = client.post(
            f"/v1/chat/sessions/{other.json()['id']}/messages",
            json={"content": "unrelated session", "client_message_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
        assert ok.status_code == 202, ok.text

    def test_memory_correct_on_barred_memory_409(self, client, auth_headers, db_session):
        _me(client, auth_headers)
        memory = _seed_memory_row(db_session, _me(client, auth_headers))
        preview = _preview(
            client,
            auth_headers,
            {"kind": "memory", "ids": [str(memory.id)], "include_history": True},
        )
        _confirm(client, auth_headers, preview, key="mem-bar-1")

        response = client.post(
            f"/v1/memory/{memory.id}/correct",
            json={"content": "user rewrite of a dying memory"},
            headers=auth_headers,
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "deletion_in_progress"

    def test_new_memory_citing_barred_event_409(self, client, auth_headers):
        _me(client, auth_headers)
        event_id = _seed_anchor_event(client, auth_headers, upstream_id="assignment:hw-m")
        _confirm_source_event(client, auth_headers, event_id, key="mem-bar-2")

        blocked = client.post(
            "/v1/memory",
            json={"content": "new memory citing a dying event", "source_event_ids": [event_id]},
            headers=auth_headers,
        )
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["error"]["code"] == "deletion_in_progress"

        fine = client.post("/v1/memory", json={"content": "unrelated"}, headers=auth_headers)
        assert fine.status_code == 201, fine.text


# ------------------------------------------------------- §2.4 run / action --


class TestRunLifecycleCodes:
    def test_chat_run_under_session_barrier_settles_cancelled(
        self, client, auth_headers, db_session
    ):
        session = client.post("/v1/chat/sessions", json={"title": None}, headers=auth_headers)
        session_id = session.json()["id"]
        sent = client.post(
            f"/v1/chat/sessions/{session_id}/messages",
            json={"content": "hello", "client_message_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
        assert sent.status_code == 202, sent.text
        sent_body = sent.json()
        assert sent_body is not None
        run_id = uuid.UUID(sent_body["run_id"])

        preview = _preview(
            client,
            auth_headers,
            {"kind": "source", "source_kind": "chat_session", "ids": [session_id]},
        )
        _confirm(client, auth_headers, preview, key="run-bar-1")

        provider = FakeToolProvider([ModelTurn(text="unused")])
        run = asyncio.run(execute_run(db_session, run_id=run_id, provider=provider))
        assert run is not None
        assert run.status == "CANCELLED"
        assert run.failure is not None
        assert run.failure["code"] == "source_deleted"
        assert run.failure["retryable"] is False
        assert provider.calls == 0  # never dispatched

    def test_generation_move_during_model_call_cancels_without_writeback(
        self, client, auth_headers, db_session
    ):
        from backend.services.model_consent import set_consent

        user_id = _me(client, auth_headers)
        set_consent(db_session, user_id, enabled=True, consent_text_version="v1")
        session = client.post("/v1/chat/sessions", json={"title": None}, headers=auth_headers)
        session_id = session.json()["id"]
        sent = client.post(
            f"/v1/chat/sessions/{session_id}/messages",
            json={"content": "hello", "client_message_id": str(uuid.uuid4())},
            headers=auth_headers,
        )
        sent_body = sent.json()
        assert sent_body is not None
        run_id = uuid.UUID(sent_body["run_id"])

        class MidflightBumpProvider(FakeToolProvider):
            async def generate_with_tools(self, input_text, instructions, tool_schemas):
                await super().generate_with_tools(input_text, instructions, tool_schemas)
                # A destructive confirm lands while the provider works.
                dl.bump_data_generation(db_session, user_id)
                return ModelTurn(text="stale answer that must not land")

        provider = MidflightBumpProvider([ModelTurn(text="unused")])
        run = asyncio.run(execute_run(db_session, run_id=run_id, provider=provider))
        assert provider.calls == 1
        assert run is not None
        assert run.status == "CANCELLED"
        assert run.failure is not None
        assert run.failure["code"] == "source_deleted"
        # Old results are never written back: no result, no assistant reply.
        assert run.result is None
        assert (
            db_session.scalars(select(ChatMessage).where(ChatMessage.agent_run_id == run.id)).all()
            == []
        )

    def test_confirmed_action_under_barrier_fails_with_lifecycle_code(
        self, client, auth_headers, db_session
    ):
        user_id = _me(client, auth_headers)
        event_id = _seed_anchor_event(client, auth_headers, upstream_id="assignment:hw-a")
        _confirm_source_event(client, auth_headers, event_id, key="act-bar-1")

        run = AgentRun(
            user_id=user_id,
            status="SUCCEEDED",
            invocation_kind="chat",
            trigger_ref={"kind": "chat"},
            operation_key=f"test:{uuid.uuid4().hex}",
            attempt_no=1,
            runner_version="t",
            tool_registry_version="t",
            prompt_version="v1",
        )
        db_session.add(run)
        db_session.flush()
        action = PendingAction(
            user_id=user_id,
            agent_run_id=run.id,
            tool_name="task.create",
            tool_version="1",
            tool_title="创建任务",
            action="task.create",
            required_level=2,
            args={"title": "复习"},
            args_hash=uuid.uuid4().hex,
            display={"summary": "创建任务"},
            basis={
                "basis_version": "v1",
                "summary": "cites a deleted event",
                "references": [{"kind": "event", "id": event_id, "label": "e", "locator": {}}],
                "rule_versions": {},
                "selected_tool_call_ids": [],
            },
            status="CONFIRMED",
            version=1,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
            idempotency_key=f"test:{uuid.uuid4().hex}",
            attempt_count=0,
            max_attempts=3,
        )
        db_session.add(action)
        db_session.flush()

        settled = asyncio.run(dispatch_confirmed_action(db_session, action_id=action.id))
        assert settled is not None and settled.last_error is not None
        assert settled.status == "FAILED"
        assert settled.last_error["code"] == "source_deleted"


# ------------------------------------------------- extraction / projection --


class TestExtractionAndProjectionGuards:
    def test_extraction_skips_file_under_deletion_barrier(
        self, client, auth_headers, db_session, storage
    ):
        user_id = _me(client, auth_headers)
        key = f"test/{uuid.uuid4().hex}.pdf"
        storage.put(key, b"%PDF-1.4 stub", "application/pdf")
        obj = FileObject(
            user_id=user_id,
            storage_key=key,
            filename="hw.pdf",
            content_type="application/pdf",
            size_bytes=14,
            status="uploaded",
            course_name="Linear Algebra",
        )
        db_session.add(obj)
        db_session.flush()
        preview = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "file", "ids": [str(obj.id)]}
        )
        _confirm(client, auth_headers, preview, key="file-bar-1")

        result = run_extraction(db_session, obj.id, storage)
        assert result["skipped"] == "deletion_barrier"
        assert (
            db_session.scalar(select(MaterialChunk.id).where(MaterialChunk.file_id == obj.id))
            is None
        )

    def test_embed_writeback_blocked_when_generation_moves(self, client, auth_headers, db_session):
        user_id = _me(client, auth_headers)
        db_session.add(
            GroundingConsent(
                user_id=user_id,
                course_name="Linear Algebra",
                enabled=True,
                consent_text_version="v1",
            )
        )
        obj = FileObject(
            user_id=user_id,
            storage_key=f"test/{uuid.uuid4().hex}.pdf",
            filename="hw.pdf",
            content_type="application/pdf",
            size_bytes=14,
            status="extracted",
            course_name="Linear Algebra",
        )
        db_session.add(obj)
        db_session.flush()
        chunk = MaterialChunk(
            user_id=user_id,
            file_id=obj.id,
            page=1,
            chunk_index=0,
            content="clean text",
            char_count=10,
            scanner_version="t",
            scan_status="clean",
            scan_flags=[],
        )
        db_session.add(chunk)
        db_session.flush()

        class BumpingEmbedder(FakeToolProvider):
            name = "fake"
            model_name = "fake-embed"

            async def embed_texts(self, texts: list[str]) -> EmbeddingResult:
                dl.bump_data_generation(db_session, user_id)
                return EmbeddingResult(vectors=[[0.1] * 8 for _ in texts], model="fake-embed")

        result = asyncio.run(
            embed_pending_chunks(
                db_session, BumpingEmbedder([]), user_id, "Linear Algebra", file_id=obj.id
            )
        )
        assert result["skipped"] == "deletion_barrier"
        assert result["embedded"] == 0
        db_session.refresh(chunk)
        assert chunk.embedding is None

    def test_projection_recompute_skipped_under_account_barrier(
        self, client, auth_headers, db_session
    ):
        user_id = _me(client, auth_headers)
        state = get_or_create_state(db_session, user_id)

        # Positive control: a normal recompute picks new tasks up.
        t1 = Task(user_id=user_id, title="t1", source="manual")
        db_session.add(t1)
        db_session.flush()
        mark_state_dirty(db_session, user_id)
        flush_state_recompute(db_session)
        db_session.refresh(state)
        assert state.pending_task_ids == [str(t1.id)]

        handle = dl.owner_handle_of(db_session, user_id)
        dl.raise_barrier(
            db_session,
            owner_handle=handle,
            scope=DataBarrierScope.ACCOUNT,
            raised_generation=dl.bump_data_generation(db_session, user_id),
        )
        t2 = Task(user_id=user_id, title="t2", source="manual")
        db_session.add(t2)
        db_session.flush()
        mark_state_dirty(db_session, user_id)
        flush_state_recompute(db_session)
        db_session.refresh(state)
        # Under the account barrier the projection is skipped — the
        # executor's fence owns the post-closure state, and a fresh derive
        # from dying rows must not land.
        assert state.pending_task_ids == [str(t1.id)]


# ------------------------------------------------------------ orphan ledger --


class TestDurableOrphanLedger:
    def test_file_delete_failure_leaves_durable_marker_then_drain_heals(
        self, client, auth_headers, db_session, storage, monkeypatch
    ):
        user_id = _me(client, auth_headers)
        key = f"test/{uuid.uuid4().hex}.pdf"
        storage.put(key, b"%PDF-1.4 stub", "application/pdf")
        obj = FileObject(
            user_id=user_id,
            storage_key=key,
            filename="hw.pdf",
            content_type="application/pdf",
            size_bytes=14,
            status="active",
        )
        db_session.add(obj)
        db_session.commit()

        fail = {"on": True}
        original_delete = storage.delete

        def _flaky(k):
            if fail["on"]:
                raise RuntimeError("object backend down")
            original_delete(k)

        monkeypatch.setattr(storage, "delete", _flaky)
        response = client.delete(f"/v1/files/{obj.id}", headers=auth_headers)
        assert response.status_code == 204, response.text

        marker = db_session.scalar(
            select(StorageOrphanKey).where(StorageOrphanKey.storage_key == key)
        )
        assert marker is not None and marker.state.value == "PENDING"
        assert storage.exists(key)  # the object survived the failed delete

        # Healing pass: the drain claims from the DB ledger (no Redis), the
        # now-working backend deletes the object and drops the marker.
        from backend.worker import tasks as worker_tasks

        fail["on"] = False
        monkeypatch.setattr(worker_tasks, "get_storage", lambda: storage)
        monkeypatch.setattr(worker_tasks, "session_scope", lambda: _session_ctx(db_session))
        summary = asyncio.run(worker_tasks.drain_storage_orphans())
        assert summary == {"deleted": 1}
        assert (
            db_session.scalar(select(StorageOrphanKey).where(StorageOrphanKey.storage_key == key))
            is None
        )
        assert not storage.exists(key)

    def test_success_path_releases_marker_inline(self, client, auth_headers, db_session, storage):
        user_id = _me(client, auth_headers)
        key = f"test/{uuid.uuid4().hex}.pdf"
        storage.put(key, b"%PDF-1.4 stub", "application/pdf")
        obj = FileObject(
            user_id=user_id,
            storage_key=key,
            filename="hw.pdf",
            content_type="application/pdf",
            size_bytes=14,
            status="active",
        )
        db_session.add(obj)
        db_session.commit()

        response = client.delete(f"/v1/files/{obj.id}", headers=auth_headers)
        assert response.status_code == 204, response.text
        # Happy path: the pre-commit marker is released inline — no
        # residue, no cron dependency.
        assert db_session.scalars(select(StorageOrphanKey)).all() == []
        assert not storage.exists(key)

    def test_marker_registration_is_idempotent_and_ladder_parks_failed(self, db_session):
        key = f"test/{uuid.uuid4().hex}"
        register_storage_orphan(db_session, key)
        register_storage_orphan(db_session, key)
        rows = db_session.scalars(select(StorageOrphanKey)).all()
        assert len(rows) == 1

        claimed = claim_due_storage_orphans(db_session)
        assert [row.storage_key for row in claimed] == [key]
        row = claimed[0]
        row.attempts = 5  # ladder-exhausted shape
        fail_storage_orphan(db_session, row.id, error_summary="object delete failed: Fake")
        db_session.refresh(row)
        assert row.state.value == "FAILED"
        assert row.next_retry_at is None
        assert row.last_error == "object delete failed: Fake"
        # A FAILED marker is not claimable again (operator surface).
        assert claim_due_storage_orphans(db_session) == []

        release_storage_orphan(db_session, key)
        assert db_session.scalars(select(StorageOrphanKey)).all() == []


# ------------------------------------------ account closure / E7-3 behavior --


class TestAccountClosureAndAnchoredTransientEdits:
    def test_account_closure_ends_suppression_rows_but_keeps_receipts(
        self, client, auth_headers, db_session, storage
    ):
        user_id = _me(client, auth_headers)
        event_id = _seed_anchor_event(client, auth_headers, upstream_id="assignment:hw-z")
        _confirm_source_event(client, auth_headers, event_id, key="acc-sup-1")
        handle = dl.owner_handle_of(db_session, user_id)
        assert db_session.scalars(
            select(DataSuppression).where(DataSuppression.owner_handle == handle)
        ).all()

        preview = _preview(client, auth_headers, {"kind": "account"})
        effects = {effect["resource_type"]: effect for effect in preview["effects"]}
        assert effects["data_suppressions"]["delete_count"] == 1
        assert effects["data_suppressions"]["reason_code"] == "account_termination"

        operation = _confirm(client, auth_headers, preview, key="account-1")
        row = db_session.scalar(
            select(DataOperation).where(DataOperation.id == uuid.UUID(operation["id"]))
        )
        redis_client = redis_lib.Redis.from_url(
            get_settings().redis_url, decode_responses=True, socket_timeout=2
        )
        run_deletion(db_session, row, storage=storage, redis=redis_client)
        assert row.status.value == "COMPLETED", (
            row.status.value,
            row.error_code,
            [
                (i.resource_type, i.state.value, i.last_error)
                for i in db_session.scalars(
                    select(DataCleanupItem).where(DataCleanupItem.operation_id == row.id)
                ).all()
                if i.state.value != "DONE"
            ],
        )

        assert (
            db_session.scalars(
                select(DataSuppression).where(DataSuppression.owner_handle == handle)
            ).all()
            == []
        )
        # The receipt outlives the account (90d window) — the other ledger
        # tables deliberately stay out of the closure.
        assert db_session.scalar(select(DataReceipt).where(DataReceipt.owner_handle == handle))

    def test_anchored_task_with_edited_projection_still_whole_deletes(
        self, client, auth_headers, db_session, storage
    ):
        user_id = _me(client, auth_headers)
        event_id = _seed_anchor_event(
            client,
            auth_headers,
            upstream_id="assignment:hw-e73",
            event_type="study.assignment.discovered",
        )
        derived = db_session.scalar(
            select(Task).where(
                Task.user_id == user_id, Task.source_upstream_id == "assignment:hw-e73"
            )
        )
        assert derived is not None  # the D-028 handler projected it
        # A user edit landed in the sync gap: the projection fields were
        # rewritten locally before the deletion confirm arrived.
        derived.title = "my own edited title"
        db_session.flush()

        preview = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        effects = {effect["resource_type"]: effect for effect in preview["effects"]}
        assert effects["tasks"]["delete_count"] == 1
        assert effects["tasks"]["reason_code"] == "anchored_derivation"

        operation = _confirm(client, auth_headers, preview, key="anchored-e73-1")
        row = db_session.scalar(
            select(DataOperation).where(DataOperation.id == uuid.UUID(operation["id"]))
        )
        run_deletion(db_session, row, storage=storage)
        assert row.status.value == "COMPLETED"
        assert db_session.get(Task, derived.id) is None
        assert db_session.get(Event, uuid.UUID(event_id)) is None
