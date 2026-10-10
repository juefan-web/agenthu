"""P0-3 slice 2: the durable cleanup executor (four phases, ladder, verify).

Covers the frozen §2.5 semantics end-to-end: phase checkpoints and resumption,
the payload-first redact routing (adjudication ② — wrong routes refuse, redact
never deletes rows), the erasure-evidence trichotomy (only a confirmed 404
counts; 403/network park retryable), FAILED parking with the barrier staying
up, manual retry re-queuing onto the SAME operation, and the account
settlement (users row gone, audit scrubbed in place, redis membership removed,
export staging invalidated, receipt surviving).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
import redis as redis_lib
from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session, sessionmaker

from backend.config import get_settings
from backend.models.audit import AuditLog
from backend.models.data_lifecycle import (
    DataBarrier,
    DataCleanupItem,
    DataOperation,
    DataReceipt,
)
from backend.models.enums import (
    CleanupItemAction,
    CleanupItemState,
    DataBarrierState,
    DataOperationStatus,
)
from backend.models.event import Event
from backend.models.focus_session import FocusSession
from backend.models.memory import Memory
from backend.models.task import Task, task_events
from backend.models.user import User
from backend.services import data_lifecycle as dl
from backend.services.data_executor import (
    ItemExecutionError,
    execute_cleanup_item,
    run_deletion,
)
from backend.services.data_exports import staging_key
from backend.services.storage import InMemoryStorage, get_storage
from backend.worker.tasks import run_data_operation
from tests.fixtures.payloads import assignment_event

from .test_data_api import _confirm, _effects, _me, _preview, _seed_citing_memory
from .test_data_lifecycle import _deletion_request, _object_spec

pytestmark = pytest.mark.integration


def _redis() -> redis_lib.Redis:
    return redis_lib.Redis.from_url(
        get_settings().redis_url, decode_responses=True, socket_timeout=2
    )


def _anchored_event(client, headers, *, upstream: str) -> str:
    payload = dict(assignment_event())
    payload["provenance"] = {"connector": "test", "upstream_id": upstream}
    response = client.post("/v1/events", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _run(db_session: Session, operation_id, *, redis_client=None) -> DataOperation:
    operation = db_session.get(DataOperation, operation_id)
    assert operation is not None
    run_deletion(db_session, operation, storage=get_storage(), redis=redis_client)
    db_session.flush()
    return operation


def _clear_gates(db_session: Session, operation_id) -> None:
    """Force every backoff gate open (the sweep's due-check, simulated)."""

    for item in db_session.scalars(
        select(DataCleanupItem).where(DataCleanupItem.operation_id == operation_id)
    ).all():
        if item.next_retry_at is not None:
            item.next_retry_at = datetime.now(UTC)
    db_session.flush()


class TestSourceDeletionExecution:
    def test_four_phases_complete_and_partition_survives(self, client, auth_headers, db_session):
        """Adjudication ① executed: the anchored task dies with its focus
        sessions, the user-correlated manual task survives with its edge
        removed, and the barrier releases on completion."""

        me = _me(client, auth_headers)
        user_id = uuid.UUID(me["id"])
        event_id = _anchored_event(client, auth_headers, upstream="exec/assign-1")
        derived = Task(
            user_id=user_id,
            title="derived",
            source="manual",
            source_upstream_id="exec/assign-1",
        )
        db_session.add(derived)
        db_session.flush()
        db_session.add(
            FocusSession(user_id=user_id, task_id=derived.id, started_at=datetime.now(UTC))
        )
        manual = Task(user_id=user_id, title="my own", source="manual")
        db_session.add(manual)
        db_session.flush()
        db_session.execute(insert(task_events).values(task_id=manual.id, event_id=event_id))
        memory_id = _seed_citing_memory(db_session, user_id, event_id)
        db_session.flush()
        derived_id, manual_id = derived.id, manual.id

        preview = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        assert _effects(preview)["tasks"]["reason_code"] == "anchored_derivation"
        operation = _confirm(client, auth_headers, preview, key="exec-run-1")
        operation_id = uuid.UUID(operation["id"])
        db_session.expire_all()

        result = _run(db_session, operation_id)

        assert result.status == DataOperationStatus.COMPLETED
        assert result.phase is not None and result.phase.value == "DELETE_VERIFY"
        assert result.outstanding_count == 0
        assert result.progress_processed == result.progress_total
        # Drop stale identity-map instances first: rows this session created
        # but the executor deleted would raise on any later refresh. Scalar
        # selects then assert absence without touching the identity map.
        db_session.expunge_all()
        assert db_session.scalar(select(Event.id).where(Event.id == uuid.UUID(event_id))) is None
        assert db_session.scalar(select(Task.id).where(Task.id == derived_id)) is None
        focus_left = db_session.execute(
            select(func.count()).select_from(FocusSession).where(FocusSession.task_id == derived_id)
        ).scalar_one()
        assert focus_left == 0, "focus sessions cascade with the anchored task"
        surviving = db_session.get(Task, manual_id)
        assert surviving is not None and surviving.title == "my own"
        edge = db_session.execute(
            select(task_events.c.task_id).where(task_events.c.task_id == manual_id)
        ).first()
        assert edge is None, "the correlation edge dies, the task does not"
        assert db_session.scalar(select(Memory.id).where(Memory.id == memory_id)) is None

        barrier = db_session.scalar(
            select(DataBarrier).where(DataBarrier.operation_id == operation_id)
        )
        assert barrier is not None and barrier.state == DataBarrierState.RELEASED

    def test_object_failure_walks_backoff_to_retry_wait(
        self, client, auth_headers, db_session, monkeypatch
    ):
        from backend.models.file import FileObject

        me = _me(client, auth_headers)
        user_id = uuid.UUID(me["id"])
        key = f"objects/{uuid.uuid4()}"
        storage = get_storage()
        storage.put(key, b"blob", "application/octet-stream")
        db_session.add(FileObject(user_id=user_id, storage_key=key, filename="a.pdf"))
        db_session.flush()
        preview = _preview(
            client,
            auth_headers,
            {
                "kind": "source",
                "source_kind": "file",
                "ids": [str(db_session.scalars(select(FileObject.id)).one())],
            },
        )
        operation = _confirm(client, auth_headers, preview, key="exec-obj-1")
        operation_id = uuid.UUID(operation["id"])
        db_session.expire_all()

        real_delete = storage.delete

        def broken_delete(broken_key: str) -> None:
            raise RuntimeError("storage down")

        monkeypatch.setattr(storage, "delete", broken_delete)
        result = _run(db_session, operation_id)
        assert result.status == DataOperationStatus.RETRY_WAIT
        assert result.next_retry_at is not None

        monkeypatch.setattr(storage, "delete", real_delete)
        _clear_gates(db_session, operation_id)
        result = _run(db_session, operation_id)
        assert result.status == DataOperationStatus.COMPLETED
        assert storage.stat(key) == storage.STAT_ABSENT

    def test_verify_forbidden_is_not_absence(self, client, auth_headers, db_session, monkeypatch):
        """The trichotomy (A-draft §2.5): a 403 can never certify erasure —
        the verify item stays retryable instead of DONE."""

        from backend.models.file import FileObject

        me = _me(client, auth_headers)
        user_id = uuid.UUID(me["id"])
        key = f"objects/{uuid.uuid4()}"
        storage = get_storage()
        storage.put(key, b"blob", "application/octet-stream")
        file_id = uuid.uuid4()
        db_session.add(FileObject(id=file_id, user_id=user_id, storage_key=key, filename="a.pdf"))
        db_session.flush()
        preview = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "file", "ids": [str(file_id)]}
        )
        operation = _confirm(client, auth_headers, preview, key="exec-verify-1")
        operation_id = uuid.UUID(operation["id"])
        db_session.expire_all()

        # Object delete "succeeds" but the verify HEAD says 403.
        real_stat = storage.stat
        monkeypatch.setattr(storage, "stat", lambda k: storage.STAT_FORBIDDEN)
        # delete stays REAL: the object is genuinely gone, and the verify
        # still refuses to settle — that is the trichotomy under test.
        result = _run(db_session, operation_id)
        assert result.status == DataOperationStatus.RETRY_WAIT
        verify_items = [
            item
            for item in db_session.scalars(
                select(DataCleanupItem).where(DataCleanupItem.operation_id == operation_id)
            ).all()
            if item.action == CleanupItemAction.VERIFY_ABSENT
            and item.resource_type == "storage_objects"
        ]
        assert verify_items and all(item.last_error for item in verify_items)

        # Healing the permission makes the same item verify cleanly.
        monkeypatch.setattr(storage, "stat", real_stat)
        _clear_gates(db_session, operation_id)
        result = _run(db_session, operation_id)
        assert result.status == DataOperationStatus.COMPLETED


class TestRedactRouting:
    def test_wrong_route_refuses_to_run(self, db_session):
        """Adjudication ② unit pin: a redact payload on a NON-audit family
        refuses execution — routing it through row deletion would destroy
        rows the 90-day receipt must keep."""

        item = DataCleanupItem(
            operation_id=uuid.uuid4(),
            owner_handle="0" * 16,
            resource_type="events",
            item_ref="events:redact",
            action=CleanupItemAction.DELETE_RELATIONAL,
            payload={"redact": True, "ids": [str(uuid.uuid4())]},
        )
        with pytest.raises(ItemExecutionError) as raised:
            execute_cleanup_item(db_session, item, storage=get_storage())
        assert raised.value.retryable is False

    def test_account_redact_keeps_rows_and_scrubs(self, client, auth_headers, db_session):
        me = _me(client, auth_headers)
        user_id = uuid.UUID(me["id"])
        audit_id = uuid.uuid4()
        db_session.add(
            AuditLog(
                id=audit_id,
                user_id=user_id,
                actor="user",
                action="data.export.download",
                resource_id="r-1",
                path="/v1/somewhere",
                ip_address="10.0.0.9",
                user_agent="test-agent",
                details={"hint": "payload"},
            )
        )
        db_session.flush()
        preview = _preview(client, auth_headers, {"kind": "account"})
        operation = _confirm(client, auth_headers, preview, key="exec-account-1")
        operation_id = uuid.UUID(operation["id"])
        db_session.expire_all()

        result = _run(db_session, operation_id, redis_client=_redis())

        assert result.status == DataOperationStatus.COMPLETED
        row = db_session.get(AuditLog, audit_id)
        assert row is not None, "redact keeps the 90-day receipt row"
        assert row.details == {} or row.details is None
        assert row.path is None and row.resource_id is None
        assert row.ip_address is None and row.user_agent is None
        db_session.expunge_all()
        assert db_session.scalar(select(User.id).where(User.id == user_id)) is None
        receipt = db_session.scalar(select(DataReceipt))
        assert receipt is not None, "the receipt outlives the users row"

    def test_redact_scan_catches_rows_the_closure_never_saw(self, client, auth_headers, db_session):
        """External review #5 pin: the deletion flow's own audit rows (written
        after the closure enumerated — e.g. the confirm request's middleware
        row) escape every frozen id list; the executor must scan at execution
        time. Born-anonymous rows never match the scan — the shared forensic
        trail keeps its IPs."""

        me = _me(client, auth_headers)
        user_id = uuid.UUID(me["id"])
        db_session.add(AuditLog(user_id=user_id, actor="user", action="seed.before"))
        db_session.flush()
        preview = _preview(client, auth_headers, {"kind": "account"})
        operation = _confirm(client, auth_headers, preview, key="exec-scan-1")
        late = AuditLog(
            user_id=user_id,
            actor="user",
            action="post /v1/data/deletions",
            path="/v1/data/deletions",
            ip_address="10.0.0.10",
            user_agent="test-agent",
            details={"hint": "late"},
        )
        anon = AuditLog(
            user_id=None,
            actor="anonymous",
            action="post /v1/auth/login",
            path="/v1/auth/login",
            ip_address="10.0.0.11",
            user_agent="anon-agent",
            details={"hint": "anon"},
        )
        db_session.add_all([late, anon])
        db_session.flush()
        db_session.expire_all()

        result = _run(db_session, uuid.UUID(operation["id"]), redis_client=_redis())

        assert result.status == DataOperationStatus.COMPLETED
        late_row = db_session.get(AuditLog, late.id)
        assert late_row is not None, "redact keeps the 90-day receipt row"
        assert late_row.user_id is None, "the users-row CASCADE ran (orphan scope proved)"
        assert late_row.path is None and late_row.resource_id is None
        assert late_row.ip_address is None and late_row.user_agent is None
        assert late_row.details is None or late_row.details == {}
        anon_row = db_session.get(AuditLog, anon.id)
        assert anon_row.ip_address == "10.0.0.11", "born-anonymous rows are not in scope"
        assert anon_row.path == "/v1/auth/login"
        assert anon_row.details == {"hint": "anon"}

    def test_redact_owner_scan_is_time_unbounded_pre_cascade(self, db_session):
        """The owner branch must not lean on the watermark: any owner-linked
        row — however old — is redacted while the users row still exists.
        The watermark only bounds the post-cascade orphan branch."""

        owner = uuid.uuid4()
        db_session.add(
            User(
                id=owner,
                email=f"audit-scan-{owner.hex[:10]}@example.com",
                display_name="Audit Scan Owner",
                hashed_password="not-a-real-hash",
            )
        )
        db_session.flush()
        old = AuditLog(
            user_id=owner,
            actor="user",
            action="old.action",
            path="/v1/old",
            ip_address="10.0.0.12",
            details={"hint": "old"},
            created_at=datetime.now(UTC) - timedelta(days=30),
        )
        db_session.add(old)
        db_session.flush()
        item = DataCleanupItem(
            operation_id=uuid.uuid4(),
            owner_handle="0" * 16,
            resource_type="audit_logs",
            item_ref="audit_logs:redact",
            action=CleanupItemAction.DELETE_RELATIONAL,
            payload={
                "redact": True,
                "ids": [],
                "scan": {
                    "owner_user_id": str(owner),
                    "watermark": datetime.now(UTC).isoformat(),
                },
            },
        )

        execute_cleanup_item(db_session, item, storage=get_storage())

        row = db_session.get(AuditLog, old.id)
        assert row.user_id == owner, "no cascade here — the owner link stays"
        assert row.path is None and row.ip_address is None
        assert row.details is None or row.details == {}

    def test_redact_orphan_branch_is_watermark_bounded(self, db_session):
        """Post-cascade orphans are locatable ONLY through the watermark:
        an in-window orphan (actor='user', user_id gone, created after the
        preview) is redacted; an older orphan belongs to someone else's
        frozen-ids coverage and stays."""

        now = datetime.now(UTC)
        fresh_orphan = AuditLog(
            user_id=None,
            actor="user",
            action="post /v1/data/deletions",
            path="/v1/data/deletions",
            ip_address="10.0.0.13",
            details={"hint": "fresh"},
            created_at=now,
        )
        old_orphan = AuditLog(
            user_id=None,
            actor="user",
            action="old.other.deletion",
            path="/v1/elsewhere",
            ip_address="10.0.0.14",
            details={"hint": "old"},
            created_at=now - timedelta(days=1),
        )
        db_session.add_all([fresh_orphan, old_orphan])
        db_session.flush()
        item = DataCleanupItem(
            operation_id=uuid.uuid4(),
            owner_handle="0" * 16,
            resource_type="audit_logs",
            item_ref="audit_logs:redact",
            action=CleanupItemAction.DELETE_RELATIONAL,
            payload={
                "redact": True,
                "ids": [],
                "scan": {
                    "owner_user_id": str(uuid.uuid4()),
                    "watermark": now.isoformat(),
                },
            },
        )

        execute_cleanup_item(db_session, item, storage=get_storage())

        fresh = db_session.get(AuditLog, fresh_orphan.id)
        assert fresh.path is None and fresh.ip_address is None
        stale = db_session.get(AuditLog, old_orphan.id)
        assert stale.path == "/v1/elsewhere", "pre-watermark orphans stay out of scope"
        assert stale.ip_address == "10.0.0.14"


class TestFailureAndManualRetry:
    def test_failed_item_parks_operation_and_barrier_stays_then_retry_requeues(
        self, client, auth_headers, db_session, monkeypatch
    ):
        event_id = _anchored_event(client, auth_headers, upstream="exec/assign-3")
        preview = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        operation = _confirm(client, auth_headers, preview, key="exec-fail-1")
        operation_id = uuid.UUID(operation["id"])
        db_session.expire_all()

        from backend.services import data_executor as dex

        real_delete_rows = dex._delete_rows

        def refusing_delete_rows(session, resource_type, ids):
            raise ItemExecutionError("simulated hard failure", retryable=False)

        monkeypatch.setattr(dex, "_delete_rows", refusing_delete_rows)
        result = _run(db_session, operation_id)
        assert result.status == DataOperationStatus.FAILED
        assert result.error_code == "cleanup_item_failed"
        assert result.outstanding_count > 0
        barrier = db_session.scalar(
            select(DataBarrier).where(DataBarrier.operation_id == operation_id)
        )
        assert barrier is not None and barrier.state == DataBarrierState.ACTIVE, (
            "FAILED never lifts a barrier"
        )

        # Manual retry (route semantics): same operation, version bump, a
        # fresh ladder — then the healed executor completes and releases.
        monkeypatch.setattr(dex, "_delete_rows", real_delete_rows)
        failed_version = result.version
        response = client.post(
            f"/v1/data/operations/{operation['id']}/retry",
            json={"expected_version": failed_version},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        retried = response.json()
        assert retried["status"] == "QUEUED"
        assert retried["version"] == failed_version + 1
        db_session.expire_all()
        result = _run(db_session, operation_id)
        assert result.status == DataOperationStatus.COMPLETED
        db_session.expire_all()
        barrier = db_session.scalar(
            select(DataBarrier).where(DataBarrier.operation_id == operation_id)
        )
        assert barrier.state == DataBarrierState.RELEASED

    def test_retry_version_conflict_is_409(self, client, auth_headers):
        event_id = _anchored_event(client, auth_headers, upstream="exec/assign-4")
        preview = _preview(
            client, auth_headers, {"kind": "source", "source_kind": "event", "ids": [event_id]}
        )
        operation = _confirm(client, auth_headers, preview, key="exec-ver-1")
        response = client.post(
            f"/v1/data/operations/{operation['id']}/retry",
            json={"expected_version": 99},
            headers=auth_headers,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "version_conflict"


class TestAccountSettlement:
    def test_account_run_invalidates_exports_and_redis_membership(
        self, client, auth_headers, db_session
    ):
        from backend.services.data_exports import create_export, run_export

        me = _me(client, auth_headers)
        user_id = uuid.UUID(me["id"])
        handle = dl.owner_handle_of(db_session, user_id)

        # A READY export with a staged package that must die with the
        # account, plus a redis wake-up membership to remove.
        user = db_session.get(User, user_id)
        export_operation, _created = create_export(
            db_session, user=user, client_request_id="exec-export-1", include_files=False
        )
        run_export(db_session, export_operation, storage=get_storage())
        db_session.flush()
        assert export_operation.status == DataOperationStatus.READY
        package_key = staging_key(handle, export_operation.id)
        assert get_storage().stat(package_key) == get_storage().STAT_EXISTS

        redis_client = _redis()
        redis_client.sadd("agenthu:trigger:dirty", str(user_id))
        assert redis_client.sismember("agenthu:trigger:dirty", str(user_id))

        preview = _preview(client, auth_headers, {"kind": "account"})
        operation = _confirm(client, auth_headers, preview, key="exec-account-2")
        operation_id = uuid.UUID(operation["id"])
        db_session.expire_all()

        result = _run(db_session, operation_id, redis_client=redis_client)

        assert result.status == DataOperationStatus.COMPLETED
        assert db_session.get(User, user_id) is None
        db_session.expire(export_operation, ["status", "error_code"])
        assert export_operation.status == DataOperationStatus.FAILED
        assert export_operation.error_code == "invalidated_by_deletion"
        assert get_storage().stat(package_key) == get_storage().STAT_ABSENT
        assert not redis_client.sismember("agenthu:trigger:dirty", str(user_id))
        receipt = db_session.scalar(select(DataReceipt))
        assert receipt is not None


class TestConcurrentDispatch:
    """P0-5 slice 3: double dispatch of one operation (a lost enqueue plus a
    sweep re-dispatch) through the real worker entry on two threads — the
    in-process stand-in for two worker processes. Item claims are exclusive
    under SKIP LOCKED, so each object is deleted exactly once and the
    operation converges no matter how the two drives interleave.

    Setup commits on a dedicated connection (the db_session fixture's outer
    transaction is invisible to the worker's own session_scope sessions),
    and the rows are cleaned up in finally — the session-scoped engine keeps
    tables across tests, so committed leftovers would leak into other tests."""

    def test_double_dispatch_deletes_each_object_once(self, engine, monkeypatch) -> None:
        handle = f"conc-{uuid.uuid4().hex}"[:32]
        refs = [f"objects/conc-{index}" for index in range(3)]

        class _CountingStorage(InMemoryStorage):
            def __init__(self) -> None:
                super().__init__()
                self.deleted: list[str] = []

            def delete(self, key: str) -> None:
                self.deleted.append(key)
                super().delete(key)

        storage = _CountingStorage()
        for ref in refs:
            storage.put(ref, b"payload", "application/octet-stream")
        monkeypatch.setattr("backend.worker.tasks.get_storage", lambda: storage)

        operation_id: uuid.UUID | None = None
        try:
            with engine.connect() as connection, connection.begin():
                session = Session(bind=connection, expire_on_commit=False)
                operation, _ = dl.get_or_create_operation(
                    session, handle, _deletion_request({"kind": "source", "ids": refs})
                )
                dl.enqueue_cleanup_items(session, operation, [_object_spec(ref) for ref in refs])
                operation_id = operation.id
            assert operation_id is not None

            # Bind the worker entry's session_scope to THIS test engine. CI
            # points DATABASE_URL and TEST_DATABASE_URL at different
            # databases; the production factory would read the other one,
            # find no operation and silently delete nothing (the first CI
            # run failed exactly that way — empty deletes, no errors).
            factory = sessionmaker(bind=engine, expire_on_commit=False)

            @contextmanager
            def _engine_scope() -> Iterator[Session]:
                session = factory()
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()

            monkeypatch.setattr("backend.worker.tasks.session_scope", _engine_scope)

            def _drive() -> None:
                asyncio.run(run_data_operation(None, str(operation_id)))

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(_drive) for _ in range(2)]
                for future in futures:
                    future.result()  # neither drive may raise

            # Exactly-once effect: every object deleted, none twice.
            assert sorted(storage.deleted) == sorted(refs)
            with engine.connect() as connection:
                states = connection.execute(
                    text(
                        "SELECT state, attempts FROM data_cleanup_items WHERE operation_id = :oid"
                    ),
                    {"oid": str(operation_id)},
                ).all()
                operation_status = connection.execute(
                    text("SELECT status FROM data_operations WHERE id = :oid"),
                    {"oid": str(operation_id)},
                ).scalar_one()
            assert operation_status == DataOperationStatus.COMPLETED.value
            assert {state for state, _ in states} == {CleanupItemState.DONE.value}
            assert {attempts for _, attempts in states} == {1}
        finally:
            if operation_id is not None:
                with engine.connect() as connection, connection.begin():
                    connection.execute(
                        text("DELETE FROM data_cleanup_items WHERE operation_id = :oid"),
                        {"oid": str(operation_id)},
                    )
                    connection.execute(
                        text("DELETE FROM data_operations WHERE id = :oid"),
                        {"oid": str(operation_id)},
                    )
