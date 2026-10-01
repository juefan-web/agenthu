"""Planner v2 + estimate learning (D-031 §1/§4) — the server-side twin of the
E4 e2e scenario. Deterministic despite wall-clock: plans are generated with an
explicit morning `start_at` and the class sits at a fixed 14:00–15:40 local.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.config import get_settings

pytestmark = pytest.mark.integration

_TZ = ZoneInfo(get_settings().default_timezone)
_TOMORROW_DEADLINE = (datetime.now(_TZ) + timedelta(days=1)).strftime("%Y-%m-%dT23:59:00+08:00")
_TODAY = datetime.now(_TZ).strftime("%Y-%m-%d")
_MORNING_START = f"{_TODAY}T10:00:00+08:00"


def _assignment(course: str, course_name: str, homework: str) -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "client_event_id": f"p2:{uuid.uuid4().hex}:{homework}",
        "type": "study.assignment.discovered",
        "occurred_at": now,
        "source": "onethu",
        "data": {
            "assignment_id": f"{course}-{homework}",
            "course_id": course,
            "course_name": course_name,
            "title": f"作业{homework}",
            "content": "planner v2 test",
            "publish_time": now,
            "deadline": _TOMORROW_DEADLINE,
            "deadline_raw": _TOMORROW_DEADLINE,
            "submitted": False,
            "graded": False,
            "url": "https://learn.example.com/p2",
        },
        "context": {},
        "provenance": {
            "connector": "onethu",
            "connector_version": "test",
            "upstream_id": f"p2:{uuid.uuid4().hex}:{homework}",
            "semantic_version": "v1",
            "fetched_at": now,
        },
    }


def _schedule_event(course_name: str) -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "client_event_id": f"p2:{uuid.uuid4().hex}:schedule",
        "type": "time.schedule.entry",
        "occurred_at": now,
        "source": "onethu",
        "data": {
            "course_name": course_name,
            "teacher": None,
            "date": _TODAY,
            "day_of_week": None,
            "start_section": None,
            "end_section": None,
            "location": "六教",
            "week_text": None,
            "category": None,
            "start_time": "14:00",
            "end_time": "15:40",
        },
        "context": {},
        "provenance": {
            "connector": "onethu",
            "connector_version": "test",
            "upstream_id": f"p2:{uuid.uuid4().hex}:schedule",
            "semantic_version": "v1",
            "fetched_at": now,
        },
    }


def _post_events(client, headers, events: list[dict]) -> None:
    response = client.post(
        "/v1/events/batch", json={"events": events, "client_cursor": None}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["rejected"] == [], response.text


def _tasks(client, headers) -> dict[str, dict]:
    listing = client.get("/v1/tasks?limit=200", headers=headers).json()
    by_title: dict[str, dict] = {}
    for task in listing:
        by_title[task["title"]] = task
    return by_title


def _complete_focus(client, headers, task_id: str, actual_minutes: int, note: str) -> None:
    session = client.post("/v1/focus-sessions", json={"task_id": task_id}, headers=headers).json()
    patched = client.patch(
        f"/v1/focus-sessions/{session['id']}",
        json={"status": "completed", "actual_minutes": actual_minutes, "deviation_note": note},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text


def _seed_course_history(client, headers, course_name: str, actuals: list[int]) -> None:
    _post_events(
        client,
        headers,
        [
            _assignment("course-x", course_name, tag)
            for tag in (f"H{i}" for i in range(len(actuals)))
        ],
    )
    for task, minutes in zip(
        [t for title, t in _tasks(client, headers).items() if title.startswith(course_name)],
        actuals,
        strict=True,
    ):
        _complete_focus(client, headers, task["id"], minutes, "planner v2 seed")


def _generate(client, headers) -> dict:
    response = client.post("/v1/plans/generate", json={"start_at": _MORNING_START}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_plan_avoids_schedule_and_carries_learned_basis(client, auth_headers) -> None:
    course_x = f"线性代数P2-{uuid.uuid4().hex[:6]}"
    course_y = f"数据结构P2-{uuid.uuid4().hex[:6]}"
    _post_events(
        client,
        auth_headers,
        [
            _assignment("course-x", course_x, "A"),
            _assignment("course-x", course_x, "B"),
            _assignment("course-x", course_x, "D"),
            _assignment("course-y", course_y, "C"),
            _schedule_event(course_x),
        ],
    )
    tasks = _tasks(client, auth_headers)
    _complete_focus(client, auth_headers, tasks[f"{course_x}：作业A"]["id"], 60, "seed")
    _complete_focus(client, auth_headers, tasks[f"{course_x}：作业B"]["id"], 90, "seed")

    plan = _generate(client, auth_headers)
    by_title = {item["title"]: item for item in plan["items"]}

    # (a) No item overlaps today's 14:00–15:40 class (buffer is internal and
    # only pushes items further away).
    class_start = datetime.fromisoformat(f"{_TODAY}T14:00:00+08:00")
    class_end = datetime.fromisoformat(f"{_TODAY}T15:40:00+08:00")
    for item in plan["items"]:
        start = datetime.fromisoformat(item["start_at"])
        end = datetime.fromisoformat(item["end_at"])
        assert end <= class_start or start >= class_end, item["title"]

    # (b) Human reasons, no internal identifiers.
    for item in plan["items"]:
        assert item["reason"]
        assert "slots_v2" not in item["reason"]
        assert "deadline_then_priority" not in item["reason"]

    # (c) Course history drives the estimate: median of 60/90 = 75.
    item_d = by_title[f"{course_x}：作业D"]
    assert item_d["basis"]["estimate_source"] == "learned:course"
    assert item_d["basis"]["estimate_minutes"] == 75
    assert item_d["basis"]["sample_count"] == 2
    assert "预计 75 分钟" in item_d["reason"]
    assert "同课程作业实际用时" in item_d["reason"]

    # (d) No course history: the honest default.
    item_c = by_title[f"{course_y}：作业C"]
    assert item_c["basis"]["estimate_source"] == "default"
    assert item_c["basis"]["estimate_minutes"] == 60

    # Learning memory: L1 episode with evidence + L2 course row.
    memories = client.get("/v1/memory?limit=200", headers=auth_headers).json()["items"]
    episodes = [m for m in memories if m["kind"] == "episode" and course_x in m["content"]]
    assert episodes, "L1 episodes for the course should exist"
    assert any(e["evidence"] and e["evidence"][0]["type"] == "event" for e in episodes)
    facts = [
        m
        for m in memories
        if m.get("subject_key") == f"estimate:course:{course_x}" and m["supersedes_id"] is None
    ]
    assert facts, "L2 course estimate row should exist"
    assert facts[0]["source"]["sample_count"] == 2
    assert facts[0]["source"]["value"] == 75


def test_estimate_ladder_user_explicit_wins(client, auth_headers) -> None:
    task = client.post(
        "/v1/tasks",
        json={"title": "Manual with estimate", "estimated_duration_minutes": 45},
        headers=auth_headers,
    ).json()
    plan = _generate(client, auth_headers)
    item = next(i for i in plan["items"] if i["task_id"] == task["id"])
    assert item["basis"]["estimate_source"] == "user"
    assert item["basis"]["estimate_minutes"] == 45


def test_ratio_ladder_counts_only_planned_completions(client, auth_headers) -> None:
    # Three tasks estimated 60, planned together, completed with actuals
    # 90/60/60 -> ratios 1.5/1.0/1.0 -> trimmed mean (n<4: no trim) 7/6.
    ids = []
    for index in range(3):
        created = client.post(
            "/v1/tasks",
            json={"title": f"Ratio task {index}", "estimated_duration_minutes": 60},
            headers=auth_headers,
        ).json()
        ids.append(created["id"])
    plan = _generate(client, auth_headers)
    client.post(f"/v1/plans/{plan['id']}/confirm", headers=auth_headers)
    for task_id, actual in zip(ids, [90, 60, 60], strict=True):
        _complete_focus(client, auth_headers, task_id, actual, "ratio seed")

    memories = client.get("/v1/memory?limit=200", headers=auth_headers).json()["items"]
    ratio_rows = [
        m
        for m in memories
        if m.get("subject_key") == "estimate_ratio:user" and m["supersedes_id"] is None
    ]
    assert ratio_rows
    assert ratio_rows[0]["source"]["sample_count"] == 3

    fresh = client.post(
        "/v1/tasks", json={"title": "Unplanned courseless"}, headers=auth_headers
    ).json()
    plan2 = _generate(client, auth_headers)
    item = next(i for i in plan2["items"] if i["task_id"] == fresh["id"])
    assert item["basis"]["estimate_source"] == "learned:ratio"
    assert item["basis"]["estimate_minutes"] == 70  # round_half_up(60 * 7/6)

    # Erratum: focus completions outside any plan contribute nothing — an
    # unplanned completion must not add a ratio sample (count stays 3).
    other = client.post("/v1/tasks", json={"title": "Seed only"}, headers=auth_headers).json()
    _complete_focus(client, auth_headers, other["id"], 120, "no plan")
    ratio_after = next(
        m
        for m in client.get("/v1/memory?limit=200", headers=auth_headers).json()["items"]
        if m.get("subject_key") == "estimate_ratio:user" and m["supersedes_id"] is None
    )
    assert ratio_after["source"]["sample_count"] == 3


def test_rejected_estimate_row_blocks_rederivation(client, auth_headers) -> None:
    course = f"拒绝课-{uuid.uuid4().hex[:6]}"
    _seed_course_history(client, auth_headers, course, [60, 90])
    key = f"estimate:course:{course}"
    # History rows share the subject_key; lifecycle actions target the live row.
    row = next(
        m
        for m in client.get("/v1/memory?limit=200", headers=auth_headers).json()["items"]
        if m.get("subject_key") == key and m["supersedes_id"] is None
    )
    rejected = client.post(f"/v1/memory/{row['id']}/reject", headers=auth_headers)
    assert rejected.status_code == 200

    # A third completion would change the median; the REJECTED placeholder
    # must block re-derivation (§5) and the reader must fall back.
    _post_events(client, auth_headers, [_assignment("course-x", course, "H2")])
    tasks = _tasks(client, auth_headers)
    third = next(
        t for title, t in tasks.items() if title.startswith(course) and t["status"] == "todo"
    )
    _complete_focus(client, auth_headers, third["id"], 120, "blocked")

    still = next(
        m
        for m in client.get("/v1/memory?limit=200", headers=auth_headers).json()["items"]
        if m.get("subject_key") == key and m["supersedes_id"] is None
    )
    assert still["correction_status"] == "REJECTED"
    assert still["supersedes_id"] is None  # blocked: not superseded, not recreated

    _post_events(client, auth_headers, [_assignment("course-x", course, "D")])
    plan = _generate(client, auth_headers)
    item_d = next(i for i in plan["items"] if i["title"].startswith(course) and "D" in i["title"])
    assert item_d["basis"]["estimate_source"] == "default"


def test_plans_status_filter_accepts_client_enum(client, auth_headers) -> None:
    client.post("/v1/tasks", json={"title": "HW"}, headers=auth_headers)
    generated = _generate(client, auth_headers)
    manual = client.post(
        "/v1/plans",
        json={"title": "Manual", "items": []},
        headers=auth_headers,
    ).json()
    client.post(f"/v1/plans/{generated['id']}/confirm", headers=auth_headers)
    client.post(f"/v1/plans/{manual['id']}/cancel", headers=auth_headers)

    # Client enum (lowercase) and internal spelling both work (D-009).
    for spelling in ("draft", "DRAFT"):
        listing = client.get(f"/v1/plans?status={spelling}", headers=auth_headers)
        assert listing.status_code == 200, listing.text
        assert listing.json()["total"] == 0  # nothing draft: one confirmed, one cancelled
    superseded = client.get("/v1/plans?status=superseded", headers=auth_headers).json()
    assert superseded["total"] == 1  # the cancelled plan maps to client "superseded"
    confirmed = client.get("/v1/plans?status=confirmed", headers=auth_headers).json()
    assert confirmed["total"] == 1
    assert client.get("/v1/plans?status=nonsense", headers=auth_headers).status_code == 422
