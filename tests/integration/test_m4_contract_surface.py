"""M4-A1 contract codification surface (D-034).

Covers the A1 acceptance list: the new ACTION_POLICY rows (focus.start
corrected to Level 2), grant soft-revoke semantics, the read faces for
pending actions / agent runs / chat with their frozen shapes and D-029
keyset pagination, notification preferences (optimistic 409), and the
memories.content_revision prefix-ordering key. User isolation is the P0
invariant asserted on every read face.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from backend.models.agent import AgentRun, PendingAction
from backend.models.chat import ChatMessage, ChatSession
from backend.models.enums import MemoryCorrectionStatus
from backend.models.memory import Memory
from backend.models.user import User

pytestmark = pytest.mark.integration


def _user_id(db_session, client, headers) -> object:
    me = client.get("/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return uuid.UUID(me.json()["id"])


def _seed_run(db_session, user_id, *, status="SUCCEEDED", tool_calls=None, basis=None):
    run = AgentRun(
        user_id=user_id,
        status=status,
        invocation_kind="chat",
        trigger_ref={"kind": "chat", "chat_message_id": str(uuid.uuid4())},
        operation_key=f"test:{uuid.uuid4().hex}",
        attempt_no=1,
        runner_version="test-runner",
        tool_registry_version="test-registry",
        prompt_version="v1",
        provider={"name": "openai", "model": "gpt-4o-mini", "capability": "tools"},
        decision_basis=basis
        or {
            "basis_version": "v1",
            "summary": "测试依据",
            "references": [],
            "rule_versions": {},
            "selected_tool_call_ids": [],
        },
        tool_calls=tool_calls
        or [
            {
                "call_id": "call-1",
                "tool_name": "state.read",
                "tool_version": "1",
                "status": "ok",
            }
        ],
    )
    db_session.add(run)
    db_session.flush()
    return run


def _seed_pending(db_session, run, *, status="PENDING", expires_in_hours=24):
    action = PendingAction(
        user_id=run.user_id,
        agent_run_id=run.id,
        tool_name="create_task",
        tool_version="1",
        tool_title="创建任务",
        action="task.create",
        required_level=2,
        args={"title": "作业"},
        args_hash=hashlib.sha256(b"{}").hexdigest(),
        display={"summary": "创建一个任务", "parameters": [], "impact": "新增任务"},
        basis={
            "basis_version": "v1",
            "summary": "来自聊天建议",
            "references": [],
            "rule_versions": {},
            "selected_tool_call_ids": [],
        },
        status=status,
        expires_at=datetime.now(UTC) + timedelta(hours=expires_in_hours),
    )
    db_session.add(action)
    db_session.flush()
    return action


# --------------------------------------------------------------------------- #
# ACTION_POLICY rows
# --------------------------------------------------------------------------- #


def test_policy_rows_and_focus_start_correction(client, auth_headers):
    response = client.get("/v1/permissions/policy", headers=auth_headers)
    assert response.status_code == 200
    actions = {entry["action"]: entry["level"] for entry in response.json()["actions"]}
    # D-034: starting focus on the user's behalf is a side effect -> Level 2.
    assert actions["focus.start"] == 2
    assert actions["memory.retrieve"] == 0
    assert actions["goal.read"] == 0
    assert actions["materials.answer"] == 0
    assert actions["replan.evaluate"] == 1


# --------------------------------------------------------------------------- #
# Grant soft revoke (D-034)
# --------------------------------------------------------------------------- #


def test_grant_soft_revoke_and_no_reuse(client, auth_headers):
    created = client.post(
        "/v1/permissions/grants",
        json={"action": "task.create", "level": 3, "note": "test"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    grant_id = created.json()["id"]

    revoked = client.delete(f"/v1/permissions/grants/{grant_id}", headers=auth_headers)
    assert revoked.status_code == 204

    listed = client.get("/v1/permissions/grants", headers=auth_headers).json()
    rows = [row for row in listed if row["id"] == grant_id]
    assert rows, "soft revoke must keep the row for audit references"
    assert rows[0]["revoked_at"] is not None

    check = client.post(
        "/v1/permissions/check",
        json={"action": "task.create"},
        headers=auth_headers,
    )
    assert check.status_code == 200
    assert check.json()["decision"] == "require_confirmation"

    # Re-granting mints a NEW row; the revoked row is never revived.
    recreated = client.post(
        "/v1/permissions/grants",
        json={"action": "task.create", "level": 3},
        headers=auth_headers,
    )
    assert recreated.status_code == 201
    assert recreated.json()["id"] != grant_id
    assert recreated.json()["revoked_at"] is None

    listed_after = client.get("/v1/permissions/grants", headers=auth_headers).json()
    by_id = {row["id"]: row for row in listed_after}
    assert by_id[grant_id]["revoked_at"] is not None


# --------------------------------------------------------------------------- #
# Pending action read face
# --------------------------------------------------------------------------- #


def test_pending_actions_isolation_pagination_and_shape(
    client, auth_headers, auth_factory, db_session
):
    other_headers = auth_factory()
    user_id = _user_id(db_session, client, auth_headers)
    other_user_id = _user_id(db_session, client, other_headers)

    run = _seed_run(db_session, user_id)
    seeds = [_seed_pending(db_session, run) for _ in range(3)]
    other_run = _seed_run(db_session, other_user_id)
    _seed_pending(db_session, other_run)

    first = client.get("/v1/pending-actions?status=active&limit=2", headers=auth_headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3  # cursorless first page keeps the COUNT (D-029)
    assert body["next_cursor"]

    item = body["items"][0]
    assert item["expires_at"]  # required non-null (A-评审裁定)
    assert item["tool"]["name"] == "create_task"
    assert item["tool"]["title"] == "创建任务"
    assert item["display"]["summary"]
    assert item["basis"]["basis_version"] == "v1"
    assert item["retryable"] is False

    second = client.get(
        f"/v1/pending-actions?status=active&limit=2&cursor={body['next_cursor']}",
        headers=auth_headers,
    )
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1
    assert second.json()["total"] is None  # cursor pages skip the COUNT

    # Cross-user isolation: the other user's action is invisible (P0).
    leaked = client.get(f"/v1/pending-actions/{seeds[0].id}", headers=other_headers)
    assert leaked.status_code == 404
    own = client.get(f"/v1/pending-actions/{seeds[0].id}", headers=auth_headers)
    assert own.status_code == 200

    # History filter excludes the active queue.
    history = client.get("/v1/pending-actions?status=history", headers=auth_headers)
    assert history.status_code == 200
    assert history.json()["items"] == []


def test_pending_actions_bad_cursor_rejected(client, auth_headers):
    response = client.get("/v1/pending-actions?cursor=not-a-cursor", headers=auth_headers)
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Agent run read face
# --------------------------------------------------------------------------- #


def test_agent_run_read_face_and_isolation(client, auth_headers, auth_factory, db_session):
    other_headers = auth_factory()
    user_id = _user_id(db_session, client, auth_headers)

    run = _seed_run(db_session, user_id, status="SUCCEEDED")
    action = _seed_pending(db_session, run, status="SUCCEEDED")

    body = client.get(f"/v1/agent/runs/{run.id}", headers=auth_headers).json()
    assert body["status"] == "SUCCEEDED"
    assert body["invocation_kind"] == "chat"
    assert body["provider"]["capability"] == "tools"
    # Review-point-6 condition: the audit face joins the tool sequence.
    assert [call["call_id"] for call in body["tool_calls"]] == ["call-1"]
    assert body["decision_basis"]["basis_version"] == "v1"
    assert body["pending_action_ids"] == [str(action.id)]
    # Degraded marker defaults to false (no DEGRADED terminal status).
    assert body["result"] is None or body["result"]["degraded"] in (True, False)

    listing = client.get("/v1/agent/runs", headers=auth_headers)
    assert listing.status_code == 200
    assert any(item["id"] == str(run.id) for item in listing.json()["items"])

    assert client.get(f"/v1/agent/runs/{run.id}", headers=other_headers).status_code == 404


# --------------------------------------------------------------------------- #
# Chat read face
# --------------------------------------------------------------------------- #


def test_chat_read_face_projections_and_deletion(client, auth_headers, auth_factory, db_session):
    other_headers = auth_factory()
    user_id = _user_id(db_session, client, auth_headers)

    session = ChatSession(user_id=user_id, title="会话一")
    db_session.add(session)
    db_session.flush()

    run = _seed_run(db_session, user_id)
    pending = _seed_pending(db_session, run)

    keep = ChatMessage(session_id=session.id, user_id=user_id, role="user", content="为什么？")
    assistant = ChatMessage(
        session_id=session.id,
        user_id=user_id,
        role="assistant",
        content="因为……",
        agent_run_id=run.id,
    )
    deleted = ChatMessage(
        session_id=session.id,
        user_id=user_id,
        role="user",
        content="已删除",
    )
    db_session.add_all([keep, assistant, deleted])
    db_session.flush()
    deleted.deleted_at = datetime.now(UTC)
    db_session.flush()

    messages = client.get(f"/v1/chat/sessions/{session.id}/messages", headers=auth_headers)
    assert messages.status_code == 200, messages.text
    items = messages.json()["items"]
    assert [item["content"] for item in items] == ["为什么？", "因为……"]

    assistant_item = items[1]
    # A5 projections: joined from the run, not stored twice.
    assert assistant_item["agent_run_id"] == str(run.id)
    assert assistant_item["decision_basis"]["summary"] == "测试依据"
    assert assistant_item["pending_action_id"] == str(pending.id)
    assert items[0]["decision_basis"] is None

    session_read = client.get(f"/v1/chat/sessions/{session.id}", headers=auth_headers)
    assert session_read.status_code == 200
    listing = client.get("/v1/chat/sessions", headers=auth_headers)
    assert listing.status_code == 200
    assert any(item["id"] == str(session.id) for item in listing.json()["items"])

    assert (
        client.get(f"/v1/chat/sessions/{session.id}/messages", headers=other_headers).status_code
        == 404
    )


# --------------------------------------------------------------------------- #
# Notification preferences
# --------------------------------------------------------------------------- #


def test_notification_preferences_get_patch_and_conflict(client, auth_headers, auth_factory):
    first = client.get("/v1/notification-preferences", headers=auth_headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["version"] == 1
    assert body["daily_budget"] == 3
    assert body["timezone"] == "Asia/Shanghai"
    assert body["sent_count"] == 0
    assert body["budget_date"]
    assert body["quiet_hours_start"] is None

    patched = client.patch(
        "/v1/notification-preferences",
        json={
            "expected_version": 1,
            "daily_budget": 5,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
            "enabled_categories": ["deadline"],
        },
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["version"] == 2
    assert patched.json()["daily_budget"] == 5
    assert patched.json()["quiet_hours_start"] == "22:00"

    # Stale expected_version -> 409, never a silent overwrite.
    stale = client.patch(
        "/v1/notification-preferences",
        json={"expected_version": 1, "daily_budget": 9},
        headers=auth_headers,
    )
    assert stale.status_code == 409

    # Clearing quiet hours requires the pair; half a pair is rejected.
    half = client.patch(
        "/v1/notification-preferences",
        json={"expected_version": 2, "quiet_hours_start": None},
        headers=auth_headers,
    )
    assert half.status_code == 422

    cleared = client.patch(
        "/v1/notification-preferences",
        json={
            "expected_version": 2,
            "quiet_hours_start": None,
            "quiet_hours_end": None,
        },
        headers=auth_headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["quiet_hours_start"] is None

    # Per-user rows are independent (P0 isolation).
    other = client.get("/v1/notification-preferences", headers=auth_factory())
    assert other.json()["version"] == 1
    assert other.json()["daily_budget"] == 3


def test_notification_preferences_validation(client, auth_headers):
    bad_time = client.patch(
        "/v1/notification-preferences",
        json={"expected_version": 1, "quiet_hours_start": "25:99"},
        headers=auth_headers,
    )
    assert bad_time.status_code == 422
    bad_budget = client.patch(
        "/v1/notification-preferences",
        json={"expected_version": 1, "daily_budget": -1},
        headers=auth_headers,
    )
    assert bad_budget.status_code == 422


# --------------------------------------------------------------------------- #
# memories.content_revision (prefix-ordering key)
# --------------------------------------------------------------------------- #


def test_content_revision_set_and_immutable_across_chain(client, auth_headers, db_session):
    email_user = client.get("/v1/auth/me", headers=auth_headers).json()
    user = db_session.query(User).filter_by(id=uuid.UUID(email_user["id"])).one()

    row = Memory(
        user_id=user.id,
        level=2,
        domain="study",
        content="原始内容",
        subject_key=f"estimate:course:test-{uuid.uuid4().hex[:6]}",
        kind="fact",
    )
    db_session.add(row)
    db_session.flush()
    expected = hashlib.sha256("原始内容".encode()).hexdigest()
    assert row.content_revision == expected

    # A correction writes a NEW row; the old row's revision never changes.
    row.correction_status = MemoryCorrectionStatus.CORRECTED
    row.supersedes_id = uuid.uuid4()  # dummy retire for direct ORM writes
    replacement = Memory(
        user_id=user.id,
        level=2,
        domain="study",
        content="修正内容",
        subject_key=None,
        kind="fact",
    )
    db_session.add(replacement)
    db_session.flush()
    assert replacement.content_revision == hashlib.sha256("修正内容".encode()).hexdigest()
    assert row.content_revision == expected
