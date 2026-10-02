from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.config import get_settings
from backend.db.base import utcnow
from backend.models.enums import PlanStatus
from backend.models.plan import Plan, PlanItem
from backend.services.current_state import pending_tasks
from backend.services.planner import _generate_v2_items, _nothing_placeable
from tests.fixtures.payloads import task_payload

pytestmark = pytest.mark.integration


def _make_task(client, headers, *, title: str, days: int) -> dict:
    return client.post(
        "/v1/tasks",
        json=task_payload(title=title, deadline=datetime.now(UTC) + timedelta(days=days)),
        headers=headers,
    ).json()


_LOCAL_TZ = ZoneInfo(get_settings().default_timezone)


def _skip_late_night(minutes_needed: int) -> None:
    """Planner v2 caps placement by the day's remaining minutes (D-027
    formula), so near local midnight an honest plan may be empty. Tests that
    need real placement skip in that window instead of flaking."""

    now = datetime.now(_LOCAL_TZ)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if (midnight - now).total_seconds() // 60 < minutes_needed:
        pytest.skip(f"late-night window: less than {minutes_needed} minutes left today")


def test_manual_plan_create_read_confirm_cancel(client, auth_headers) -> None:
    task = _make_task(client, auth_headers, title="Read chapter 2", days=1)
    created = client.post(
        "/v1/plans",
        json={
            "title": "Tonight",
            "permission_level": 2,
            "basis": {"reason": "user created"},
            "items": [
                {
                    "title": "Read chapter 2",
                    "task_id": task["id"],
                    "order_index": 0,
                    "planned_minutes": 45,
                }
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan["status"] == "draft"
    assert plan["confirmation_required"] is True
    assert plan["generated_at"] is not None
    assert len(plan["items"]) == 1
    # Manual items without explicit times are backfilled so the client
    # contract (non-null start_at/end_at) always holds.
    assert plan["items"][0]["start_at"] is not None
    assert plan["items"][0]["end_at"] is not None

    fetched = client.get(f"/v1/plans/{plan['id']}", headers=auth_headers)
    assert fetched.status_code == 200

    confirmed = client.post(f"/v1/plans/{plan['id']}/confirm", headers=auth_headers)
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["confirmation_required"] is False

    confirmed_at = confirmed.json()["confirmed_at"]
    retried = client.post(f"/v1/plans/{plan['id']}/confirm", headers=auth_headers)
    assert retried.status_code == 200
    assert retried.json()["status"] == "confirmed"
    assert retried.json()["confirmed_at"] == confirmed_at

    other = client.post(
        "/v1/plans", json={"title": "Draft", "items": []}, headers=auth_headers
    ).json()
    cancelled = client.post(f"/v1/plans/{other['id']}/cancel", headers=auth_headers)
    assert cancelled.json()["status"] == "superseded"


def test_manual_plan_rejects_taskless_items(client, auth_headers) -> None:
    """The client contract has no task-less plan item, so creation rejects it."""

    response = client.post(
        "/v1/plans",
        json={"title": "Taskless", "items": [{"title": "Read chapter", "order_index": 0}]},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_generate_plan_orders_by_deadline(client, auth_headers) -> None:
    _make_task(client, auth_headers, title="Later", days=3)
    _make_task(client, auth_headers, title="Sooner", days=1)

    # Fixed morning start: the v2 available-minutes budget shrinks with the
    # wall clock, and a late-evening run could not fit both 120-minute tasks.
    morning = datetime.now(_LOCAL_TZ).strftime("%Y-%m-%dT10:00:00+08:00")
    generated = client.post("/v1/plans/generate", json={"start_at": morning}, headers=auth_headers)
    assert generated.status_code == 201, generated.text
    plan = generated.json()
    assert plan["status"] == "draft"
    assert plan["confirmation_required"] is True
    titles = [item["title"] for item in plan["items"]]
    # Both tasks appear, earlier deadline first; the 120-minute fixture
    # estimate may split each into <=90-minute blocks (order preserved).
    assert set(titles) == {"Sooner", "Later"}
    assert titles == ["Sooner"] * titles.count("Sooner") + ["Later"] * titles.count("Later")
    assert plan["basis"]["strategy"] == "slots_v2"
    # Client plan items require present start/end/reason.
    for item in plan["items"]:
        assert item["task_id"] is not None
        assert item["start_at"] is not None
        assert item["end_at"] is not None
        assert item["reason"]


def test_today_plan_generates_when_missing(client, auth_headers) -> None:
    _skip_late_night(130)
    _make_task(client, auth_headers, title="HW2", days=1)
    today = client.get("/v1/plans/today", headers=auth_headers)
    assert today.status_code == 200, today.text
    body = today.json()
    assert body["status"] == "draft"
    assert body["items"]
    # Planner v2 splits tasks longer than 90 minutes into blocks (§3.1): the
    # fixture's 120-minute estimate lands as 90 + 30 on the same task.
    assert {item["task_id"] for item in body["items"]} == {body["items"][0]["task_id"]}
    assert sum(item["planned_minutes"] for item in body["items"]) == 120


def test_today_plan_is_idempotent(client, auth_headers) -> None:
    # Late-night window: a 120-minute task no longer fits the day's remaining
    # budget, the first GET generates an *empty* draft, and D7 (empty draft +
    # pending task => not reusable) makes the second GET regenerate — the ids
    # legitimately differ near midnight.
    _skip_late_night(130)
    _make_task(client, auth_headers, title="HW2", days=1)
    first = client.get("/v1/plans/today", headers=auth_headers).json()
    second = client.get("/v1/plans/today", headers=auth_headers).json()
    assert first["id"] == second["id"]

    plans = client.get("/v1/plans", headers=auth_headers).json()
    assert plans["total"] == 1


def test_today_ignores_cross_day_draft(client, auth_headers, db_session) -> None:
    me = client.get("/v1/auth/me", headers=auth_headers).json()
    stale = Plan(
        user_id=uuid.UUID(me["id"]),
        title="Yesterday's draft",
        status=PlanStatus.PENDING_CONFIRMATION,
        created_at=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.add(stale)
    db_session.flush()

    _make_task(client, auth_headers, title="HW2", days=1)
    today = client.get("/v1/plans/today", headers=auth_headers).json()
    assert today["id"] != str(stale.id)


def test_today_never_returns_manual_plan_without_task_ids(client, auth_headers, db_session) -> None:
    # Client-invalid plans can no longer be created through the API, so seed
    # one directly (legacy rows / direct writes are the remaining source).
    me = client.get("/v1/auth/me", headers=auth_headers).json()
    manual = Plan(
        user_id=uuid.UUID(me["id"]),
        title="Manual",
        status=PlanStatus.PENDING_CONFIRMATION,
    )
    manual.items.append(PlanItem(title="Read chapter", order_index=0))
    db_session.add(manual)
    db_session.flush()

    _make_task(client, auth_headers, title="HW2", days=1)
    today = client.get("/v1/plans/today", headers=auth_headers).json()
    assert today["id"] != str(manual.id)
    for item in today["items"]:
        assert item["task_id"] is not None
        assert item["start_at"] is not None
        assert item["end_at"] is not None


def test_today_reuses_valid_plan_behind_invalid_proposals(client, auth_headers, db_session) -> None:
    """A fixed scan window must not hide the only client-valid proposal."""

    me = client.get("/v1/auth/me", headers=auth_headers).json()
    user_id = uuid.UUID(me["id"])
    task = _make_task(client, auth_headers, title="HW2", days=1)
    base = datetime.now(UTC)

    valid = Plan(
        user_id=user_id,
        title="Valid proposal",
        status=PlanStatus.PENDING_CONFIRMATION,
        created_at=base,
    )
    valid.items.append(
        PlanItem(
            task_id=uuid.UUID(task["id"]),
            title="HW2",
            order_index=0,
            planned_start=base,
            planned_end=base + timedelta(minutes=60),
            planned_minutes=60,
        )
    )
    db_session.add(valid)

    # 11 newer proposals are client-invalid (null task_id / start / end).
    for index in range(11):
        invalid = Plan(
            user_id=user_id,
            title=f"Invalid {index}",
            status=PlanStatus.PENDING_CONFIRMATION,
            created_at=base + timedelta(seconds=index + 1),
        )
        invalid.items.append(PlanItem(title="task-less", order_index=0))
        db_session.add(invalid)
    db_session.flush()

    today = client.get("/v1/plans/today", headers=auth_headers).json()
    assert today["id"] == str(valid.id)


def test_replan_supersedes_previous_plan(client, auth_headers) -> None:
    _make_task(client, auth_headers, title="HW2", days=1)
    plan = client.post("/v1/plans/generate", json={}, headers=auth_headers).json()
    client.post(f"/v1/plans/{plan['id']}/confirm", headers=auth_headers)

    replanned = client.post(
        f"/v1/plans/{plan['id']}/replan",
        json={"reason": "Finished earlier than expected", "horizon_minutes": 180},
        headers=auth_headers,
    )
    assert replanned.status_code == 201, replanned.text
    new_plan = replanned.json()
    assert new_plan["replan_reason"] == "Finished earlier than expected"
    # The replan suggestion shape is contractual (D-031 §2): the client reads
    # replaces_plan_id to detect suggestions and render the diff.
    assert new_plan["replaces_plan_id"] == plan["id"]

    original = client.get(f"/v1/plans/{plan['id']}", headers=auth_headers).json()
    assert original["status"] == "superseded"


def test_plan_item_basis_round_trip(client, auth_headers) -> None:
    task = _make_task(client, auth_headers, title="Linear algebra set", days=2)
    basis = {
        "deadline": "2026-10-03T15:59:00+08:00",
        "slack_minutes": 600,
        "estimate_minutes": 75,
        "estimate_source": "learned:course",
        "slot_reason": "longest gap between classes",
        "score": {"urgency": 3, "goal": 0, "priority": 0},
    }
    created = client.post(
        "/v1/plans",
        json={
            "title": "Tonight",
            "items": [
                {
                    "title": "Linear algebra set",
                    "task_id": task["id"],
                    "planned_minutes": 75,
                    "basis": basis,
                }
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan["items"][0]["basis"] == basis

    fetched = client.get(f"/v1/plans/{plan['id']}", headers=auth_headers).json()
    assert fetched["items"][0]["basis"] == basis


def test_plan_item_basis_serializes_object_not_null(client, auth_headers) -> None:
    _skip_late_night(130)
    # The frozen client Zod is `basis: z.record(z.unknown()).optional()` —
    # optional does not accept null, so basis must always serialize an object:
    # an empty one for manual/legacy items (recent_state pattern, D-027
    # appendix), a populated one for planner v2 items. Ordinary plans
    # serialize replaces_plan_id/replan_reason as null only because those are
    # declared `.nullable().optional()` (D-031 §2).
    _make_task(client, auth_headers, title="Bare homework", days=1)
    generated = client.get("/v1/plans/today", headers=auth_headers).json()
    assert generated["replaces_plan_id"] is None
    assert generated["replan_reason"] is None
    assert generated["items"]
    # v2-generated items carry the structured explainability payload.
    assert all(item["basis"].get("estimate_source") for item in generated["items"])

    task = generated["items"][0]
    manual = client.post(
        "/v1/plans",
        json={"title": "Manual", "items": [{"title": "Bare homework", "task_id": task["task_id"]}]},
        headers=auth_headers,
    ).json()
    assert manual["items"][0]["basis"] == {}


def test_replan_rejects_terminal_plans(client, auth_headers) -> None:
    _make_task(client, auth_headers, title="HW2", days=1)
    plan = client.post("/v1/plans/generate", json={}, headers=auth_headers).json()
    client.post(f"/v1/plans/{plan['id']}/replan", json={"reason": "first"}, headers=auth_headers)

    superseded = client.get(f"/v1/plans/{plan['id']}", headers=auth_headers).json()
    assert superseded["status"] == "superseded"

    response = client.post(
        f"/v1/plans/{plan['id']}/replan", json={"reason": "again"}, headers=auth_headers
    )
    assert response.status_code == 409


def test_plan_item_update(client, auth_headers) -> None:
    task = _make_task(client, auth_headers, title="Step 1 task", days=1)
    plan = client.post(
        "/v1/plans",
        json={"title": "Plan", "items": [{"title": "Step 1", "task_id": task["id"]}]},
        headers=auth_headers,
    ).json()
    item_id = plan["items"][0]["id"]
    response = client.patch(
        f"/v1/plans/{plan['id']}/items/{item_id}",
        json={"status": "COMPLETED", "actual_minutes": 40},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "COMPLETED"
    assert response.json()["items"][0]["actual_minutes"] == 40


def test_confirming_unknown_plan_is_404(client, auth_headers) -> None:
    response = client.post(
        "/v1/plans/00000000-0000-0000-0000-000000000000/confirm", headers=auth_headers
    )
    assert response.status_code == 404


def test_plan_cannot_reference_other_users_task(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()
    task = _make_task(client, alice, title="Alice HW", days=1)

    response = client.post(
        "/v1/plans",
        json={"title": "Bob plan", "items": [{"title": "x", "task_id": task["id"]}]},
        headers=bob,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_plan_isolation_between_users(client, auth_factory) -> None:
    alice = auth_factory()
    bob = auth_factory()
    plan = client.post("/v1/plans", json={"title": "Alice plan", "items": []}, headers=alice).json()
    assert client.get(f"/v1/plans/{plan['id']}", headers=bob).status_code == 404


def test_confirming_client_invalid_plan_is_rejected(client, auth_headers, db_session) -> None:
    """A client-invalid plan must never become the confirmed current plan.

    This is the K1 regression: a legacy/manual plan without task_id/times,
    confirmed through the API, used to be served by ``GET /v1/current-state``
    and broke the client's Zod parse. Creation now backfills/rejects such
    items; this guards the confirm path against direct DB writes.
    """

    me = client.get("/v1/auth/me", headers=auth_headers).json()
    invalid = Plan(
        user_id=uuid.UUID(me["id"]),
        title="Legacy manual plan",
        status=PlanStatus.DRAFT,
    )
    invalid.items.append(PlanItem(title="task-less", order_index=0))
    db_session.add(invalid)
    db_session.flush()

    response = client.post(f"/v1/plans/{invalid.id}/confirm", headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_current_state_never_serves_client_invalid_current_plan(
    client, auth_headers, db_session
) -> None:
    """current-state filters client-invalid confirmed plans (K1, belt+braces).

    Even if a client-invalid plan somehow reaches CONFIRMED (direct DB write,
    older data), ``GET /v1/current-state`` must not return it: the response is
    validated by the client's frozen Zod contract, which would throw.
    """

    me = client.get("/v1/auth/me", headers=auth_headers).json()
    user_id = uuid.UUID(me["id"])
    task = _make_task(client, auth_headers, title="HW2", days=1)

    invalid = Plan(
        user_id=user_id,
        title="Legacy confirmed",
        status=PlanStatus.CONFIRMED,
        confirmed_at=datetime.now(UTC),
    )
    invalid.items.append(PlanItem(title="task-less", order_index=0))
    db_session.add(invalid)

    valid = Plan(
        user_id=user_id,
        title="Valid confirmed",
        status=PlanStatus.CONFIRMED,
        confirmed_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    valid.items.append(
        PlanItem(
            task_id=uuid.UUID(task["id"]),
            title="HW2",
            order_index=0,
            planned_start=datetime.now(UTC),
            planned_end=datetime.now(UTC) + timedelta(minutes=30),
            planned_minutes=30,
        )
    )
    db_session.add(valid)
    db_session.flush()

    state = client.get("/v1/current-state", headers=auth_headers)
    assert state.status_code == 200
    current_plan = state.json()["current_plan"]
    # The newest confirmed plan is client-invalid; current-state must skip it
    # and fall through to the older, client-valid one.
    assert current_plan is not None
    assert current_plan["id"] == str(valid.id)
    for item in current_plan["items"]:
        assert item["task_id"] is not None
        assert item["start_at"] is not None
        assert item["end_at"] is not None


def test_today_regenerates_when_tasks_added_after_empty_draft(client, auth_headers) -> None:
    _skip_late_night(130)
    """An empty same-day draft must not hide newly created tasks (D7).

    ``is_client_valid_plan`` treats empty items as valid, so without the
    "items non-empty or no pending tasks" reuse condition, today would keep
    returning the empty draft until it was manually cancelled.
    """

    # No tasks yet: today produces the empty baseline draft (D-019) and
    # repeated reads stay idempotent.
    empty = client.get("/v1/plans/today", headers=auth_headers).json()
    assert empty["items"] == []
    again = client.get("/v1/plans/today", headers=auth_headers).json()
    assert again["id"] == empty["id"]

    # Adding a task must be absorbed by a fresh plan.
    task = _make_task(client, auth_headers, title="HW3", days=1)
    regenerated = client.get("/v1/plans/today", headers=auth_headers).json()
    assert regenerated["id"] != empty["id"]
    # The 120-minute fixture estimate may split into <=90-minute blocks, all
    # on the new task.
    assert {item["task_id"] for item in regenerated["items"]} == {task["id"]}

    # And the regenerated plan is the one that gets reused from now on.
    settled = client.get("/v1/plans/today", headers=auth_headers).json()
    assert settled["id"] == regenerated["id"]


def _make_suggestion(
    db_session, user_id: uuid.UUID, replaced_id: str, task_id: str, title: str
) -> Plan:
    """A replan-suggestion draft the way the M2 trigger engine will create
    one: DRAFT + replaces_plan_id, never touching the replaced plan."""

    now = datetime.now(UTC)
    plan = Plan(
        user_id=user_id,
        replaces_plan_id=uuid.UUID(replaced_id),
        title="重排建议",
        status=PlanStatus.DRAFT,
        basis={"trigger": "focus_overrun", "strategy": "deadline_then_priority"},
        permission_level=1,
        generated_by="replan_trigger",
        replan_reason="《线性代数》作业 Focus 超时 42 分钟——今日后续安排需要重排",
        items=[
            PlanItem(
                task_id=uuid.UUID(task_id),
                title=title,
                order_index=0,
                planned_start=now,
                planned_end=now + timedelta(minutes=60),
                planned_minutes=60,
            )
        ],
    )
    db_session.add(plan)
    db_session.flush()
    return plan


def test_confirming_a_replacement_supersedes_the_replaced_plan(
    client, auth_headers, db_session
) -> None:
    task = _make_task(client, auth_headers, title="HW2", days=1)
    original = client.post("/v1/plans/generate", json={}, headers=auth_headers).json()
    client.post(f"/v1/plans/{original['id']}/confirm", headers=auth_headers)

    me = client.get("/v1/auth/me", headers=auth_headers).json()
    suggestion = _make_suggestion(
        db_session, uuid.UUID(me["id"]), original["id"], task["id"], "HW2"
    )

    confirmed = client.post(f"/v1/plans/{suggestion.id}/confirm", headers=auth_headers)
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "confirmed"
    assert body["replaces_plan_id"] == original["id"]

    # Accept-means-supersede (D-031 §2): the replaced plan retired in the
    # same transaction instead of lingering as a second CONFIRMED plan.
    replaced = client.get(f"/v1/plans/{original['id']}", headers=auth_headers).json()
    assert replaced["status"] == "superseded"

    # Retry-safe: replaying confirm keeps the outcome (and must not 409 on
    # the already-superseded replacement).
    retried = client.post(f"/v1/plans/{suggestion.id}/confirm", headers=auth_headers)
    assert retried.status_code == 200
    assert retried.json()["status"] == "confirmed"
    assert (
        client.get(f"/v1/plans/{original['id']}", headers=auth_headers).json()["status"]
        == "superseded"
    )


def test_confirming_unrelated_plan_leaves_replaced_plan_alone(
    client, auth_headers, db_session
) -> None:
    # A manual draft without replaces_plan_id must not retire anything, and a
    # suggestion whose target was cancelled by hand only confirms itself.
    task_a = _make_task(client, auth_headers, title="A", days=1)
    task_b = _make_task(client, auth_headers, title="B", days=2)
    first = client.post("/v1/plans/generate", json={}, headers=auth_headers).json()
    client.post(f"/v1/plans/{first['id']}/confirm", headers=auth_headers)

    me = client.get("/v1/auth/me", headers=auth_headers).json()
    manual = client.post(
        "/v1/plans",
        json={
            "title": "Manual",
            "items": [{"title": "A", "task_id": task_a["id"], "planned_minutes": 30}],
        },
        headers=auth_headers,
    ).json()
    client.post(f"/v1/plans/{manual['id']}/confirm", headers=auth_headers)
    assert (
        client.get(f"/v1/plans/{first['id']}", headers=auth_headers).json()["status"] == "confirmed"
    )

    suggestion = _make_suggestion(db_session, uuid.UUID(me["id"]), first["id"], task_b["id"], "B")
    client.post(f"/v1/plans/{first['id']}/cancel", headers=auth_headers)
    confirmed = client.post(f"/v1/plans/{suggestion.id}/confirm", headers=auth_headers)
    assert confirmed.status_code == 200
    # The client mapping cannot distinguish CANCELLED from SUPERSEDED (both
    # "superseded"), so assert the stored status: the hand-cancelled target
    # stays CANCELLED — the idempotent skip, not an overwrite.
    row = db_session.get(Plan, uuid.UUID(first["id"]))
    assert row is not None
    assert row.status == PlanStatus.CANCELLED


def _schedule_entry(client, headers, name: str, start: str, end: str) -> None:
    now = datetime.now(UTC).isoformat()
    client.post(
        "/v1/events",
        json={
            "client_event_id": f"sched:{uuid.uuid4().hex}",
            "type": "time.schedule.entry",
            "occurred_at": now,
            "source": "onethu",
            "data": {
                "course_name": name,
                "date": datetime.now(_LOCAL_TZ).strftime("%Y-%m-%d"),
                "start_time": start,
                "end_time": end,
            },
            "context": {},
            "provenance": {
                "connector": "onethu",
                "connector_version": "test",
                "upstream_id": f"sched:{uuid.uuid4().hex}",
                "semantic_version": "v1",
                "fetched_at": now,
            },
        },
        headers=headers,
    )


def test_empty_draft_reused_when_nothing_placeable(client, auth_headers) -> None:
    """The deep-night churn ruling (D-019 appendix, 2026-10-02).

    When the day's remaining budget/slots cannot fit ANY pending task, the
    honest plan is empty — and repeated today reads must REUSE that empty
    draft instead of generating a fresh one per refresh (the churn the
    late-night flaky class projected). Forced deterministically: two schedule
    entries cover the whole working day, so nothing is placeable at any hour.
    """

    _make_task(client, auth_headers, title="HW", days=1)
    _schedule_entry(client, auth_headers, "全天课A", "08:00", "16:00")
    _schedule_entry(client, auth_headers, "全天课B", "16:00", "23:59")

    first = client.get("/v1/plans/today", headers=auth_headers).json()
    assert first["items"] == []  # the honest empty plan
    second = client.get("/v1/plans/today", headers=auth_headers).json()
    assert second["id"] == first["id"]  # reused, not churned
    third = client.get("/v1/plans/today", headers=auth_headers).json()
    assert third["id"] == first["id"]


def test_nothing_placeable_mirrors_generate_v2_items(client, auth_headers, db_session) -> None:
    """Drift pin (PR #30 review): `_nothing_placeable` must mirror the placement
    eligibility of `_generate_v2_items` — both predicates over the same fixtures.
    Divergence means an empty draft is reused while work IS placeable (hides
    tasks from today) or churns one draft per read while nothing fits."""

    user_id = uuid.UUID(client.get("/v1/auth/me", headers=auth_headers).json()["id"])

    def assert_predicates_agree() -> None:
        tasks = pending_tasks(db_session, user_id)
        placed = _generate_v2_items(db_session, user_id=user_id, tasks=tasks, start=utcnow())
        assert _nothing_placeable(db_session, user_id) == (len(placed) == 0)

    # 1. Nothing pending: both empty-draft-eligible.
    assert_predicates_agree()

    # 2. A small task that fits today's room: both placeable.
    client.post(
        "/v1/tasks",
        json={"title": "Fits", "estimated_duration_minutes": 30},
        headers=auth_headers,
    )
    assert_predicates_agree()

    # 3. Only an unplaceable task left (single block > any slot/budget): both
    # empty-eligible. Estimated 600 minutes exceeds any day budget (D-027 cap).
    first_task_id = client.get("/v1/tasks", headers=auth_headers).json()[0]["id"]
    client.delete(f"/v1/tasks/{first_task_id}", headers=auth_headers)
    client.post(
        "/v1/tasks",
        json={"title": "Too big", "estimated_duration_minutes": 600},
        headers=auth_headers,
    )
    assert_predicates_agree()
