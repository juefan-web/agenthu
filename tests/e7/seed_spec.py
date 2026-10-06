"""E7 seed world specification (declarative, deterministic, DB-free).

``build_world()`` derives the *entire* acceptance world from fixed inputs —
uuid5 stable ids, a fixed UTC anchor, sequential synthetic markers and
keystream-derived embedding vectors — so repeated builds are byte-identical.
Nothing here touches a database; ``seed.py`` applies the rows and
``manifest.py`` derives the pre-registration manifest from the same spec.

Design rulings live in AGENT_CONTEXT/TASKS/m5-e7-fixtures.md §2; the family
inventory follows m5-e7-acceptance.md §1 (U and V mirror each other: same
shapes, different owners and markers). Lifecycle ledger rows (data_*) are
deliberately NOT seeded — case drivers create them through the real API so
the ledger only ever contains rows produced by the production path.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from tests.e7.markers import marker

#: Fixed wall-clock anchor: every seeded timestamp is ``SEED_ANCHOR + offset``.
SEED_ANCHOR = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)

_EMBED_DIM = 1536
_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://agenthu.invalid/e7")

#: owner-resolvable staging prefix the export executor writes packages to.
EXPORT_STAGING_PREFIX = "exports/"


def stable_id(kind: str, user: str, name: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{kind}:{user}:{name}")


def at(offset_minutes: int) -> datetime:
    return SEED_ANCHOR + timedelta(minutes=offset_minutes)


def synthetic_vector(name: str) -> list[float]:
    """Deterministic pseudo-random unit-scale vector (not a model product)."""

    values: list[float] = []
    counter = 0
    while len(values) < _EMBED_DIM:
        digest = hashlib.sha256(f"{name}:{counter}".encode()).digest()
        for i in range(0, 64, 2):
            if len(values) >= _EMBED_DIM:
                break
            raw = int.from_bytes(digest[i : i + 2], "big") / 65535.0
            values.append(round(raw * 2 - 1, 4))
        counter += 1
    return values


@dataclass(frozen=True)
class UserSpec:
    tag: str  # "U" | "V"
    email: str
    password: str  # synthetic fixture credential, logged nowhere
    display_name: str
    user_id: uuid.UUID
    owner_handle: str  # 32-hex, matches the register-side uuid.hex shape


@dataclass(frozen=True)
class Row:
    """One insert, in exact FK-safe application order."""

    table: str
    user: str  # "U" | "V" (audit rows too; nothing user-independent today)
    values: dict[str, object]


@dataclass
class World:
    users: dict[str, UserSpec] = field(default_factory=dict)
    rows: list[Row] = field(default_factory=list)
    blobs: dict[str, bytes] = field(default_factory=dict)  # storage_key -> bytes
    marker_names: dict[str, dict[str, str]] = field(default_factory=dict)
    ids: dict[str, uuid.UUID] = field(default_factory=dict)  # "U:e1" -> id
    vector_names: list[str] = field(default_factory=list)  # "U:m2b" etc.
    blob_names: dict[str, str] = field(default_factory=dict)  # "U:f1" -> key

    def marker(self, user: str, name: str) -> str:
        """Allocate the next sequential token for ``name`` (build order)."""

        seq = len(self.marker_names[user]) + 1
        token = marker(user, seq)
        self.marker_names[user][name] = token
        return token

    def rid(self, user: str, name: str) -> uuid.UUID:
        return self.ids[f"{user}:{name}"]


def build_world() -> World:
    world = World()
    world.marker_names = {"U": {}, "V": {}}
    for tag in ("U", "V"):
        _build_user(world, tag)
    return world


def _build_user(world: World, tag: str) -> None:
    m = world.marker
    uid = stable_id("user", tag, "self")
    world.users[tag] = UserSpec(
        tag=tag,
        email=f"e7-{tag.lower()}@test.invalid",
        password=f"e7-{tag.lower()}-password-0001",
        display_name=f"E7 用户 {tag} {m(tag, 'name')}",
        user_id=uid,
        owner_handle=stable_id("owner-handle", tag, "self").hex,
    )
    rid = lambda name: stable_id("row", tag, name)  # noqa: E731 (spec-local shorthand)

    def keep(name: str, value: uuid.UUID) -> uuid.UUID:
        world.ids[f"{tag}:{name}"] = value
        return value

    e1, e2, e3 = keep("e1", rid("e1")), keep("e2", rid("e2")), keep("e3", rid("e3"))
    e4, e5, e6 = keep("e4", rid("e4")), keep("e5", rid("e5")), keep("e6", rid("e6"))
    t1, t2, t3 = keep("t1", rid("t1")), keep("t2", rid("t2")), keep("t3", rid("t3"))
    fs1 = keep("fs1", rid("fs1"))
    g1 = keep("g1", rid("g1"))
    m1 = keep("m1", rid("m1"))
    m2a, m2b = keep("m2a", rid("m2a")), keep("m2b", rid("m2b"))
    m3, m4 = keep("m3", rid("m3")), keep("m4", rid("m4"))
    p1 = keep("p1", rid("p1"))
    pi1, pi2 = keep("pi1", rid("pi1")), keep("pi2", rid("pi2"))
    f1, f2 = keep("f1", rid("f1")), keep("f2", rid("f2"))
    c1, c2 = keep("c1", rid("c1")), keep("c2", rid("c2"))
    a1 = keep("a1", rid("a1"))
    s1, s2 = keep("s1", rid("s1")), keep("s2", rid("s2"))
    cm1, cm2, cm3, cm4 = (keep(n, rid(n)) for n in ("cm1", "cm2", "cm3", "cm4"))
    r1, r2 = keep("r1", rid("r1")), keep("r2", rid("r2"))
    pa1 = keep("pa1", rid("pa1"))
    pam1 = keep("pam1", rid("pam1"))
    pg1 = keep("pg1", rid("pg1"))
    gc1 = keep("gc1", rid("gc1"))
    mcc1 = keep("mcc1", rid("mcc1"))
    np1 = keep("np1", rid("np1"))
    al1, al2, al3 = (keep(n, rid(n)) for n in ("al1", "al2", "al3"))

    R = lambda table, values: world.rows.append(Row(table, tag, values))  # noqa: E731

    def event(
        event_id: uuid.UUID,
        *,
        source: str,
        type_: str,
        occurred: datetime,
        data: dict[str, object],
        upstream: str | None,
        client_event_id: str,
    ) -> None:
        provenance: dict[str, object] = {"origin": "e7-seed"}
        if upstream is not None:
            provenance = {
                "connector": "onethu",
                "connector_version": "1",
                "upstream_id": upstream,
                "semantic_version": "1",
                "fetched_at": at(0).isoformat(),
            }
        R(
            "events",
            {
                "id": event_id,
                "user_id": uid,
                "type": type_,
                "timestamp": occurred,
                "source": source,
                "data": data,
                "context": {"origin": "e7-seed"},
                "provenance": provenance,
                "dedupe_key": f"e7:{tag}:{client_event_id}",
                "client_event_id": f"e7-{tag}-{client_event_id}",
                "ingested_at": at(0),
            },
        )

    event(
        e1,
        source="onethu",
        type_="study.assignment.created",
        occurred=at(10),
        data={
            "title": f"作业一 {m(tag, 'e1.title')}",
            "course": "线性代数",
            "due_at": at(3 * 24 * 60).isoformat(),
        },
        upstream=f"E7-{tag}-asg-1",
        client_event_id="asg-1",
    )
    event(
        e2,
        source="onethu",
        type_="study.assignment.created",
        occurred=at(12),
        data={
            "title": f"作业二 {m(tag, 'e2.title')}",
            "course": "线性代数",
            "due_at": at(7 * 24 * 60).isoformat(),
        },
        upstream=f"E7-{tag}-asg-2",
        client_event_id="asg-2",
    )
    event(
        e3,
        source="onethu",
        type_="study.assignment.created",
        occurred=at(20),
        data={
            "title": f"作业三 {m(tag, 'e3.title')}",
            "course": "线性代数",
            "due_at": at(10 * 24 * 60).isoformat(),
        },
        upstream=f"E7-{tag}-asg-3",
        client_event_id="asg-3",
    )
    # t1's title and e4's task_title snapshot get SEPARATE markers: a marker
    # string shared across rows would make absence assertions blind when one
    # row is retained user content (e4 survives an anchored delete).
    t1_title = f"完成作业一 {m(tag, 't1.title')}"
    event(
        e4,
        source="manual",
        type_="focus.finished",
        occurred=at(120),
        data={
            "task_title": f"完成作业一 {m(tag, 'e4.task_title')}",
            "minutes": 45,
            "deviation": m(tag, "e4.deviation"),
        },
        upstream=None,
        client_event_id="focus-1",
    )
    event(
        e5,
        source="manual",
        type_="study.note.added",
        occurred=at(30),
        data={"note": f"作业一用了两小时 {m(tag, 'e5.note')}"},
        upstream=None,
        client_event_id="note-1",
    )
    event(
        e6,
        source="manual",
        type_="study.note.added",
        occurred=at(40),
        data={"note": f"作业二提前完成 {m(tag, 'e6.note')}"},
        upstream=None,
        client_event_id="note-2",
    )

    R(
        "tasks",
        {
            "id": t1,
            "user_id": uid,
            "title": t1_title,
            "source": "onethu",
            "source_upstream_id": f"E7-{tag}-asg-1",
            "status": "TODO",
            "deadline": at(3 * 24 * 60),
            "estimated_duration_minutes": 60,
            "extra": {"derived": True, "course": "线性代数"},
        },
    )
    R(
        "tasks",
        {
            "id": t2,
            "user_id": uid,
            "title": f"完成作业二 {m(tag, 't2.title')}",
            "source": "onethu",
            "source_upstream_id": f"E7-{tag}-asg-2",
            "status": "TODO",
            "deadline": at(7 * 24 * 60),
            "extra": {"derived": True, "course": "线性代数"},
        },
    )
    R(
        "tasks",
        {
            "id": t3,
            "user_id": uid,
            "title": f"整理错题本 {m(tag, 't3.title')}",
            "source": "manual",
            "source_upstream_id": None,
            "status": "IN_PROGRESS",
            "extra": {"origin": "user"},
        },
    )
    R("task_events", {"task_id": t3, "event_id": e3})
    R(
        "focus_sessions",
        {
            "id": fs1,
            "user_id": uid,
            "task_id": t1,
            "status": "completed",
            "started_at": at(90),
            "ended_at": at(135),
            "actual_minutes": 45,
            "deviation_note": f"中途被消息打断一次 {m(tag, 'fs1.deviation')}",
        },
    )
    R(
        "goals",
        {
            "id": g1,
            "user_id": uid,
            "title": f"线性代数期优 {m(tag, 'g1.title')}",
            "description": f"期中前完成全部作业并复盘 {m(tag, 'g1.desc')}",
            "category": "study",
            "status": "ACTIVE",
            "priority": 1,
            "target_date": at(30 * 24 * 60),
        },
    )

    R(
        "memories",
        {
            "id": m1,
            "user_id": uid,
            "level": 1,
            "domain": "study",
            "content": f"作业一做得吃力，重看了讲义第二页 {m(tag, 'm1.content')}",
            "source": {"origin": "e7-seed"},
            "source_event_ids": [str(e3)],
            "evidence": [{"kind": "event", "id": str(e3)}],
            "confidence": 0.6,
            "correction_status": "UNREVIEWED",
        },
    )
    # L2 correction chain: v1 (m2a) was superseded by v2 (m2b) ten minutes
    # after the anchor; the old row points *at* the new one (D-032) and its
    # validity window closed then, so only m2b is live for the subject key.
    R(
        "memories",
        {
            "id": m2b,
            "user_id": uid,
            "level": 2,
            "domain": "study",
            "content": f"作业通常花两小时，常在晚自习后 {m(tag, 'm2b.content')}",
            "source": {"origin": "e7-seed"},
            "source_event_ids": [str(e5), str(e6)],
            "evidence": [{"kind": "event", "id": str(e5)}, {"kind": "event", "id": str(e6)}],
            "confidence": 0.8,
            "correction_status": "CONFIRMED",
            "subject_key": f"E7-{tag}-l2-key",
            "kind": "habit",
            "embedding": synthetic_vector(f"{tag}:m2b"),
            "valid_from": at(10),
            "valid_to": None,
            "supersedes_id": None,
        },
    )
    R(
        "memories",
        {
            "id": m2a,
            "user_id": uid,
            "level": 2,
            "domain": "study",
            "content": f"作业大约一小时 {m(tag, 'm2a.content')}",
            "source": {"origin": "e7-seed"},
            "source_event_ids": [str(e5)],
            "evidence": [],
            "confidence": 0.5,
            "correction_status": "UNREVIEWED",
            "subject_key": f"E7-{tag}-l2-key",
            "kind": "habit",
            "embedding": None,
            "valid_from": at(0),
            "valid_to": at(10),
            "supersedes_id": m2b,
        },
    )
    R(
        "memories",
        {
            "id": m3,
            "user_id": uid,
            "level": 2,
            "domain": "study",
            "content": f"喜欢把截止日提前一天 {m(tag, 'm3.content')}",
            "source": {"origin": "user"},
            "source_event_ids": [],
            "evidence": [],
            "confidence": 0.7,
            "correction_status": "CONFIRMED",
            "subject_key": f"E7-{tag}-own",
            "kind": "preference",
            "embedding": synthetic_vector(f"{tag}:m3"),
        },
    )
    R(
        "memories",
        {
            "id": m4,
            "user_id": uid,
            "level": 3,
            "domain": "study",
            "content": f"考前以错题本为主复盘 {m(tag, 'm4.content')}",
            "source": {"origin": "e7-seed"},
            "source_event_ids": [],
            "evidence": [],
            "confidence": 0.6,
            "correction_status": "UNREVIEWED",
            "subject_key": None,
            "kind": "model",
            "embedding": synthetic_vector(f"{tag}:m4"),
        },
    )
    for name in ("m2b", "m3", "m4"):
        world.vector_names.append(f"{tag}:{name}")

    R(
        "plans",
        {
            "id": p1,
            "user_id": uid,
            "title": f"本周作业计划 {m(tag, 'p1.title')}",
            "status": "CONFIRMED",
            "basis": {
                "references": [{"kind": "task", "id": str(t1)}, {"kind": "event", "id": str(e1)}],
                "note": m(tag, "p1.basis"),
            },
            "permission_level": 2,
            "generated_by": "manual",
            "confirmed_at": at(15),
        },
    )
    R(
        "plan_items",
        {
            "id": pi1,
            "plan_id": p1,
            "task_id": t1,
            "title": f"完成作业一 {m(tag, 'pi1.title')}",
            "order_index": 0,
            "planned_start": at(2 * 24 * 60),
            "planned_end": at(2 * 24 * 60 + 60),
            "planned_minutes": 60,
            "status": "PENDING",
            "basis": {"task_id": str(t1), "event_id": str(e1)},
        },
    )
    R(
        "plan_items",
        {
            "id": pi2,
            "plan_id": p1,
            "task_id": None,
            "title": f"预习下一讲 {m(tag, 'pi2.title')}",
            "order_index": 1,
            "planned_start": at(3 * 24 * 60),
            "planned_minutes": 45,
            "status": "PENDING",
            "result": {
                "note": f"已预习前两节 {m(tag, 'pi2.result')}",
                "task_id": str(t2),
                "event_id": str(e2),
            },
        },
    )
    R(
        "current_states",
        {
            "id": rid("cs1"),
            "user_id": uid,
            "version": 1,
            "current_time": at(60),
            "current_context": {
                "location": "library",
                "tz": "Asia/Shanghai",
                "marker": m(tag, "cs1.context"),
            },
            "current_task_id": t1,
            "current_plan_id": p1,
            "pending_task_ids": [str(t2)],
            "recent_state": {"focus_minutes_today": 45, "note": m(tag, "cs1.recent")},
            "available_minutes": 180,
        },
    )

    for name, filename, course, page_count in (
        ("f1", "线性代数讲义.pdf", "线性代数", 2),
        ("f2", "数据结构作业.pdf", "数据结构", 2),
    ):
        file_id = keep(name, rid(name))
        blob_marker = m(tag, f"{name}.blob")
        key = f"e7/{tag.lower()}/{name}/{file_id}"
        content = (
            f"E7 fixture blob {filename} {blob_marker}\n"
            f"{course} 讲义内容占位，供泄漏扫描使用。\n" * page_count
        ).encode()
        world.blobs[key] = content
        world.blob_names[f"{tag}:{name}"] = key
        R(
            "file_objects",
            {
                "id": file_id,
                "user_id": uid,
                "storage_key": key,
                "storage_backend": "minio",
                "filename": filename,
                "content_type": "application/pdf",
                "size_bytes": len(content),
                "checksum_sha256": hashlib.sha256(content).hexdigest(),
                "status": "active",
                "course_name": course,
            },
        )

    for name, file_id, page, text_name in (
        ("c1", f1, 1, "c1.content"),
        ("c2", f1, 2, "c2.content"),
        ("c3", f2, 1, "c3.content"),
        ("c4", f2, 2, "c4.content"),
    ):
        text = f"第{page}页：本页讲解核心概念与例题 {m(tag, text_name)}"
        R(
            "material_chunks",
            {
                "id": keep(name, rid(name)),
                "user_id": uid,
                "file_id": file_id,
                "page": page,
                "chunk_index": page - 1,
                "content": text,
                "char_count": len(text),
                "scanner_version": "e7-seed-1",
                "scan_status": "clean",
                "scan_flags": [],
                "embedding": synthetic_vector(f"{tag}:{name}"),
                "embedding_model": "e7-synthetic-1536",
            },
        )
        world.vector_names.append(f"{tag}:{name}")
    R(
        "material_answers",
        {
            "id": a1,
            "user_id": uid,
            "course_name": "线性代数",
            "question": f"行列式有哪些性质？{m(tag, 'a1.question')}",
            "answer": f"见讲义第一页：行列式基本性质共五条 {m(tag, 'a1.answer')}",
            "grounded": True,
            # citations carry file_id — the closure links answers via
            # citations[].file_id (data_closure), chunk_ids alone would not.
            "citations": [{"file_id": str(f1), "page": 1, "quote": m(tag, "a1.quote")}],
            "chunk_ids": [str(c1), str(c2)],
            "memory_ids": [str(m2b)],
            "model_version": "e7-synthetic-1",
            "prompt_version": "e7-1",
        },
    )

    R(
        "chat_sessions",
        {"id": s1, "user_id": uid, "title": f"作业讨论 {m(tag, 's1.title')}"},
    )
    R(
        "chat_sessions",
        {"id": s2, "user_id": uid, "title": f"资料问答 {m(tag, 's2.title')}"},
    )
    R(
        "chat_messages",
        {
            "id": cm1,
            "session_id": s1,
            "user_id": uid,
            "role": "user",
            "content": f"帮我看看作业一怎么下手 {m(tag, 'cm1.content')}",
            "client_message_id": f"e7-{tag}-cm1",
            "created_at": at(200),
        },
    )
    R(
        "chat_messages",
        {
            "id": cm2,
            "session_id": s1,
            "user_id": uid,
            "role": "assistant",
            "content": f"先读讲义第二页再列提纲 {m(tag, 'cm2.content')}",
            "agent_run_id": r1,
            "created_at": at(201),
        },
    )
    R(
        "chat_messages",
        {
            "id": cm3,
            "session_id": s2,
            "user_id": uid,
            "role": "user",
            "content": f"讲义里行列式在哪页 {m(tag, 'cm3.content')}",
            "client_message_id": f"e7-{tag}-cm3",
            "created_at": at(210),
        },
    )
    # Soft-deleted message (D-036 §8-2): invisibility is not deletion —
    # E7-3c asserts the content is hard-cleared with the whole session.
    R(
        "chat_messages",
        {
            "id": cm4,
            "session_id": s2,
            "user_id": uid,
            "role": "assistant",
            "content": f"在第一页 {m(tag, 'cm4.content.softdeleted')}",
            "client_message_id": f"e7-{tag}-cm4",
            "created_at": at(211),
            "deleted_at": at(220),
        },
    )

    R(
        "agent_runs",
        {
            "id": r1,
            "user_id": uid,
            "status": "SUCCEEDED",
            "invocation_kind": "chat",
            "trigger_ref": {"kind": "chat_message", "id": str(cm1)},
            "operation_key": f"chat:e7-{tag}:cm1",
            "attempt_no": 1,
            "runner_version": "e7-seed-1",
            "tool_registry_version": "e7-seed-1",
            "prompt_version": "e7-1",
            "provider": {"name": "e7-synthetic", "model": "e7-synthetic-1"},
            "context_snapshot": {
                "summary": f"正在准备线性代数作业 {m(tag, 'r1.snapshot')}",
                "task_id": str(t1),
            },
            "decision_basis": {
                "references": [{"kind": "event", "id": str(e1)}, {"kind": "task", "id": str(t1)}]
            },
            "tool_calls": [{"name": "task.create", "args_hash": "0" * 64}],
            "result": {"reply": f"建议先读讲义 {m(tag, 'r1.result')}"},
            "started_at": at(
                200,
            ),
            "finished_at": at(201),
        },
    )
    R(
        "agent_runs",
        {
            "id": r2,
            "user_id": uid,
            "status": "FAILED",
            "invocation_kind": "chat",
            "trigger_ref": {"kind": "chat_message", "id": str(cm3)},
            "operation_key": f"chat:e7-{tag}:cm3",
            "attempt_no": 1,
            "runner_version": "e7-seed-1",
            "tool_registry_version": "e7-seed-1",
            "prompt_version": "e7-1",
            "provider": {"name": "e7-synthetic", "model": "e7-synthetic-1"},
            "context_snapshot": {"summary": m(tag, "r2.snapshot")},
            "failure": {"code": "provider_unavailable", "message": "synthetic"},
            "started_at": at(210),
            "finished_at": at(211),
        },
    )
    R(
        "pending_actions",
        {
            "id": pa1,
            "user_id": uid,
            "agent_run_id": r1,
            "tool_name": "task.create",
            "tool_version": "e7-seed-1",
            "tool_title": "创建任务",
            "action": "task.create",
            "required_level": 2,
            "args": {"title": m(tag, "pa1.args")},
            "args_hash": hashlib.sha256(f"{tag}:pa1".encode()).hexdigest(),
            "display": {"title": m(tag, "pa1.display")},
            "basis": {"run_id": str(r1), "event_id": str(e1)},
            # SUCCEEDED, not CONFIRMED: the worker's dispatcher claims
            # CONFIRMED/FAILED_RETRYABLE rows and would re-execute this
            # action on its own clock (seen in the first smoke run: an
            # extra agent task + audit rows). A settled row is still full
            # user content for every deletion closure.
            "status": "SUCCEEDED",
            "version": 1,
            "expires_at": at(24 * 60),
            "confirmed_at": at(205),
            "executed_at": at(206),
            "finished_at": at(206),
            "result": {"task_id": str(t3)},
        },
    )
    R(
        "pending_action_mutations",
        {
            "id": pam1,
            "pending_action_id": pa1,
            "user_id": uid,
            "mutation_id": stable_id("mutation", tag, "pam1").hex[:32],
            "kind": "confirm",
            "response": {
                "id": str(pa1),
                "status": "CONFIRMED",
                "cached_marker": m(tag, "pam1.response"),
            },
        },
    )

    R(
        "permission_grants",
        {
            "id": pg1,
            "user_id": uid,
            "action": "plan.auto_send",
            "level": 3,
            "scope": {
                "categories": ["replan"],
                "channels": ["notification"],
                "daily_budget": 2,
                "note_marker": m(tag, "pg1.scope"),
            },
            "note": f"自动发送重排提醒 {m(tag, 'pg1.note')}",
            "granted_at": at(50),
        },
    )
    R(
        "grounding_consents",
        {
            "id": gc1,
            "user_id": uid,
            "course_name": "线性代数",
            "enabled": True,
            "consent_text_version": "v1",
            "consented_at": at(5),
        },
    )
    R(
        "model_context_consents",
        {
            "id": mcc1,
            "user_id": uid,
            "enabled": True,
            "consent_text_version": "v1",
            "consented_at": at(5),
        },
    )
    R(
        "notification_preferences",
        {
            "id": np1,
            "user_id": uid,
            "version": 1,
            "timezone": "Asia/Shanghai",
            "enabled_categories": ["replan", "deadline"],
            "quiet_hours_start": "23:00",
            "quiet_hours_end": "07:00",
            "daily_budget": 3,
            "budget_date": SEED_ANCHOR.date(),
        },
    )

    R(
        "audit_logs",
        {
            "id": al1,
            "user_id": uid,
            "action": "data.export_requested",
            "path": "/v1/data/exports",
            "details": {"marker": m(tag, "al1.details"), "task_id": str(t1)},
            "ip_address": "203.0.113.7",
            "user_agent": f"e7-agent/1 {m(tag, 'al1.ua')}",
            "created_at": at(0),
        },
    )
    R(
        "audit_logs",
        {
            "id": al2,
            "user_id": uid,
            "action": "chat.message_sent",
            "path": f"/v1/chat/sessions/{s1}/messages",
            "details": {"marker": m(tag, "al2.details")},
            "ip_address": "203.0.113.7",
            "user_agent": f"e7-agent/1 {m(tag, 'al2.ua')}",
            "created_at": at(200),
        },
    )
    R(
        "audit_logs",
        {
            "id": al3,
            "user_id": uid,
            "action": "auth.login",
            "path": "/v1/auth/login",
            "details": {"marker": m(tag, "al3.details")},
            "ip_address": "203.0.113.9",
            "user_agent": f"e7-agent/1 {m(tag, 'al3.ua')}",
            "created_at": at(0),
        },
    )


# --- pre-registered case expectations ----------------------------------------


@dataclass(frozen=True)
class ObjectExpectation:
    """Per-user object-store expectations for a case."""

    user: str
    absent_seeded: tuple[str, ...] = ()  # readable blob names ("U:f1")
    exports_min: int = 0  # staged export packages under exports/<handle>/
    exports_exact: int | None = None


@dataclass(frozen=True)
class CaseExpectation:
    case_id: str
    title: str
    operations: tuple[str, ...]
    count_deltas: dict[str, dict[str, int]] = field(default_factory=dict)
    # Lifecycle ledger families (data_*): exact row counts couple the
    # manifest to executor phase fan-out, which P0-3/P0-4 may still tune;
    # the acceptance text pins CONTENT families exactly and ledger presence
    # ("the durable ledger is not lost"). Minimums carry that semantics;
    # cleanup_ledger_drained proves no work is left outstanding.
    count_minimums: dict[str, dict[str, int]] = field(default_factory=dict)
    marker_absence: tuple[str, ...] = ()  # readable marker names
    all_markers_absent_for: tuple[str, ...] = ()  # whole-account absence
    vector_absence: tuple[str, ...] = ()  # readable vector names
    live_key_absence: tuple[str, ...] = ()  # "U:l2key" style subject keys
    object_expectations: tuple[ObjectExpectation, ...] = ()
    redis_absence: tuple[str, ...] = ()  # "U:dirty" dirty-set membership
    retained: tuple[str, ...] = ()  # allowed survivors with reasons
    invariants: tuple[str, ...] = ()  # named protocol invariants (verify.py)
    package_scan: str | None = None  # e.g. "U-only" for export packages
    blocked_by: str | None = None


EXPECTATIONS: dict[str, CaseExpectation] = {
    "E7-1": CaseExpectation(
        case_id="E7-1",
        title="U 完整导出；V 无凭据边界；并发删除作废旧包；签名能力过期不可读",
        operations=(
            "U export include_files=true → COMPLETED + download",
            "U export include_files=false → 包内明确无文件对象",
            "V 以自身凭据列/下载 U 包 → 404/403",
            # op-4 是执行轮补驱动面（同 E7-9/10 的 blocked 标注风格）：
            # 参考驱动只跑 op1-3；本条的 +1 operation 与连带账本行届时随
            # 驱动注册，现在 data_operations=2 不为它预留。
            "导出期间并发 source 删除 → 旧包作废（generation 409 语义）——执行轮补驱动",
        ),
        count_deltas={"U": {"data_operations": 2}},
        object_expectations=(ObjectExpectation(user="U", exports_exact=2),),
        package_scan="U-only",
        retained=("V 全部内容与计数不变（对照）",),
        invariants=("export_manifest_counts_match_seed",),
    ),
    "E7-2": CaseExpectation(
        case_id="E7-2",
        title="预览变化/过期/重复确认/202 丢响应/失败重试",
        operations=(
            "同 target 二次 preview → 内容变化 → digest 409",
            "preview 过期后 confirm → 409 preview_expired",
            "同 client_request_id 重放 → 同 operation（幂等）",
            "202 丢失后重发同 key → 收敛同 op，不产生第二删除",
            "注入失败后 retry → 同 operation 继续",
        ),
        # Target: chat session s2 (own fresh world per case).
        count_deltas={"U": {"chat_sessions": -1, "chat_messages": -2}},
        count_minimums={
            "U": {
                "data_operations": 1,
                "data_previews": 1,
                "data_barriers": 1,
                "data_cleanup_items": 1,
            }
        },
        marker_absence=("s2.title", "cm3.content", "cm4.content.softdeleted"),
        invariants=("cleanup_ledger_drained",),
        retained=("audit/receipt/ledger 家族按冻结规则保留",),
    ),
    "E7-3a": CaseExpectation(
        case_id="E7-3a",
        title="删除锚定源事件 e1：派生 task 整删含 focus 级联",
        operations=("U preview+confirm source event e1",),
        # current_states: the whole-delete clears U's projection row (the
        # fence owns post-closure recompute; end-state zero rows).
        count_deltas={"U": {"events": -1, "tasks": -1, "focus_sessions": -1, "current_states": -1}},
        count_minimums={
            "U": {
                "data_operations": 1,
                "data_previews": 1,
                "data_barriers": 1,
                "data_suppressions": 1,
                "data_cleanup_items": 1,
            }
        },
        marker_absence=("e1.title", "t1.title", "fs1.deviation"),
        vector_absence=(),
        retained=(
            "e4（focus 结果事件，manual 无锚）存活——e4.task_title 为独立 marker",
            "t3（manual 无锚）存活，t3↔e3 边存活",
            "plan/agent_run 中对 e1/t1 的引用失效标注，行数不变",
            "V 全部不变",
        ),
        invariants=("cleanup_ledger_drained", "invalid_basis_no_original_text"),
    ),
    "E7-3b": CaseExpectation(
        case_id="E7-3b",
        title="删除文件源 f1：chunk/embedding/引用回答整清",
        operations=("U preview+confirm source file f1",),
        count_deltas={"U": {"file_objects": -1, "material_chunks": -2, "material_answers": -1}},
        count_minimums={
            "U": {
                "data_operations": 1,
                "data_previews": 1,
                "data_barriers": 1,
                "data_cleanup_items": 1,
            }
        },
        marker_absence=("f1.blob", "c1.content", "c2.content", "a1.question", "a1.answer"),
        vector_absence=("U:c1", "U:c2"),
        object_expectations=(ObjectExpectation(user="U", absent_seeded=("U:f1",)),),
        retained=("f2 及其 chunk/向量存活", "V 全部不变"),
        invariants=("cleanup_ledger_drained",),
    ),
    "E7-3c": CaseExpectation(
        case_id="E7-3c",
        title="删除 Chat 会话 s2：含软删消息内容硬清",
        operations=("U preview+confirm source chat_session s2",),
        count_deltas={"U": {"chat_sessions": -1, "chat_messages": -2}},
        count_minimums={
            "U": {
                "data_operations": 1,
                "data_previews": 1,
                "data_barriers": 1,
                "data_cleanup_items": 1,
            }
        },
        marker_absence=("s2.title", "cm3.content", "cm4.content.softdeleted"),
        retained=("s1 及其消息存活", "V 全部不变"),
        invariants=("cleanup_ledger_drained",),
    ),
    "E7-4a": CaseExpectation(
        case_id="E7-4a",
        title="忘记 L2 最新版 m2b：superseded 旧版不复活",
        operations=("U 对 m2b 执行整链忘记（lifecycle）",),
        count_deltas={"U": {"memories": -2}},
        marker_absence=("m2b.content", "m2a.content"),
        vector_absence=("U:m2b",),
        live_key_absence=("U:E7-U-l2-key",),
        retained=("m1/m3/m4 存活", "检索/估时/live-key 判定不读失效行"),
    ),
    "E7-4b": CaseExpectation(
        case_id="E7-4b",
        title="删除 L2 源事件 e5：样本不足失效而非删除，向量零召回",
        operations=("U preview+confirm source event e5",),
        count_deltas={"U": {"events": -1}},
        # e5 是事件锚删除，与 E7-3a 同形流：五族账本按同形先例注册下限
        # （events 有锚 → suppressions +1）。
        count_minimums={
            "U": {
                "data_operations": 1,
                "data_previews": 1,
                "data_barriers": 1,
                "data_suppressions": 1,
                "data_cleanup_items": 1,
            }
        },
        marker_absence=("e5.note",),
        vector_absence=("U:m2b",),
        live_key_absence=("U:E7-U-l2-key",),
        retained=(
            "memories 行数不变（失效保留），m2a 历史版本不复活",
            "e6 仍在 m2b source_event_ids 中（id 引用非原文）",
        ),
        invariants=("invalid_basis_no_original_text",),
    ),
    "E7-5": CaseExpectation(
        case_id="E7-5",
        title="U 账号删除（含与 worker 竞态）：全域归零、账本存活、V 不受影响",
        operations=(
            "U 请求账号删除（Level 2 确认）",
            "与 worker 在 context/dispatch/embed/写回各注入竞态",
        ),
        count_deltas={
            "U": {
                "users": -1,
                "events": -6,
                "tasks": -3,
                "task_events": -1,
                "focus_sessions": -1,
                "goals": -1,
                "memories": -5,
                "plans": -1,
                "plan_items": -2,
                "current_states": -1,
                "file_objects": -2,
                "material_chunks": -4,
                "material_answers": -1,
                "chat_sessions": -2,
                "chat_messages": -4,
                "agent_runs": -2,
                "pending_actions": -1,
                "pending_action_mutations": -1,
                "permission_grants": -1,
                "grounding_consents": -1,
                "model_context_consents": -1,
                "notification_preferences": -1,
                # owner 可见口径：data_closure 的 redact 路径把 user_id
                # SET-NULL（行全局存活，owner 谓词 user_id=:uid 计数归零）。
                "audit_logs": -3,
            }
        },
        # 账本存活族（data_closure：本删除自身的行 "must survive their own
        # execution"；receipts 走 90 天窗）。previews 同样存活——closure
        # 不触碰该族，且其 owner 键是 user_id（行保留原值可数）。
        count_minimums={
            "U": {
                "data_operations": 1,
                "data_previews": 1,
                "data_barriers": 1,
                "data_cleanup_items": 1,
                "data_receipts": 1,
            }
        },
        all_markers_absent_for=("U",),
        object_expectations=(ObjectExpectation(user="U", absent_seeded=("U:f1", "U:f2")),),
        redis_absence=("U:dirty",),
        retained=(
            "audit_logs 行全局存活但 IP/UA/path/JSON 脱敏、user_id SET-NULL（§5；owner 口径归零）",
            "data_operations/previews/barriers/cleanup/receipts 账本存活"
            "（owner_handle/user 键保留原值）",
            "data_suppressions 随账号终删（data_closure ACCOUNT_TERMINATION）",
            "V 全部不变",
        ),
        invariants=(
            "account_audit_scrubbed",
            "receipt_issued_once",
            "single_effective_worker_claim",
        ),
    ),
    "E7-6": CaseExpectation(
        case_id="E7-6",
        title="Redis 断供/S3 403/进程崩溃：账本不丢、恢复同 operation",
        operations=(
            "删除 f2 期间注入 Redis 断供 → 账本仍有 key",
            "注入 S3 403 → 操作非 COMPLETED、403 不当 404",
            "恢复后继续同 operation，自动重试 ≤5，耗尽可核查",
        ),
        count_deltas={"U": {"file_objects": -1, "material_chunks": -2}},
        # data_operations 不留在 deltas：minimums 非空时 verify 的精确扫掠
        # 豁免全部生命周期族（harness 不动），deltas 键会成死键。单
        # operation 混沌幂等收敛以 ≥1 下限注册；"不产生第二 operation"
        # 由 retry_ladder_bounded 不变量与驱动断言承担。文件锚删除无
        # suppressions（同 E7-3b 形）。
        count_minimums={
            "U": {
                "data_operations": 1,
                "data_previews": 1,
                "data_barriers": 1,
                "data_cleanup_items": 1,
            }
        },
        marker_absence=("f2.blob", "c3.content", "c4.content"),
        vector_absence=("U:c3", "U:c4"),
        object_expectations=(ObjectExpectation(user="U", absent_seeded=("U:f2",)),),
        invariants=("cleanup_ledger_drained", "retry_ladder_bounded"),
    ),
    "E7-7": CaseExpectation(
        case_id="E7-7",
        title="被删来源重采不复活；解除后重授权可复用（server 面）",
        operations=(
            "删除 e1 → 同 upstream 重采（新 client_event_id）→ 409 source_deleted",
            # release 今无 HTTP 路由（write_guards §4 路由矩阵有意不设，
            # acceptance 文档已锚 P0-6 触发面）：执行轮驱动等 P0-6 路由
            # 或进程内调服务，二选一随驱动定并在此注记更新。
            "release_source_suppressions → 同 upstream 重采 → 201 新行"
            "（无 HTTP 路由——P0-6 触发面或进程内调用）",
            "换账号守卫/离线队列/Stronghold 等客户端面按 E7-7 预登记注记执行",
        ),
        # Net zero: -1 delete then +1 re-import after release. The new row
        # is a NEW event id with fresh content markers, so no U marker may
        # be asserted absent at the end state; the intermediate rejection
        # is a driver-level hard assert.
        count_deltas={"U": {"events": 0}},
        # 删除流与 E7-4b 同形（五族账本）；suppressions 的 release 是
        # UPDATE 置 released_at（durable 账本不删行，write_guards），终态
        # ≥1 而非 0——删除 e1 的 +1 不会被 release 抵消。
        count_minimums={
            "U": {
                "data_operations": 1,
                "data_previews": 1,
                "data_barriers": 1,
                "data_suppressions": 1,
                "data_cleanup_items": 1,
            }
        },
        retained=(
            "suppression 行 +1 后 release 为 UPDATE 置 released_at"
            "（行持久存活，durable 账本终态 ≥1）",
            "客户端面证据按 m5-e7-acceptance §2 E7-7 注记①-⑤",
        ),
        invariants=("suppressed_reimport_rejected", "release_reopens_anchor"),
    ),
    "E7-8": CaseExpectation(
        case_id="E7-8",
        title="grant 窄 scope/撤销竞态/两类 consent；实际渠道生效",
        operations=(
            "创建窄 scope grant → 撤销 → 到期/撤销阻发",
            "错 category/channel/window 拒绝",
            "L2 不被通知 L3 绕过；quiet hours/daily budget 独立生效",
            "notification.delivered 仅预算结算，不当远程已读",
        ),
        count_deltas={"U": {"permission_grants": 0}},
        retained=(
            "既有 pg1 保留；新 grant 走 API 创建后撤销（净 0）",
            "consent 行数不变（状态翻转）",
        ),
        invariants=("grant_revocation_blocks_send",),
    ),
    "E7-9": CaseExpectation(
        case_id="E7-9",
        title="2API+2worker 共享限流/恢复、trace 链、敏感 marker 扫描",
        operations=("待 P0-5 观测面落地后执行",),
        blocked_by="P0-5",
        invariants=("shared_rate_limit_not_doubled", "trace_linkage", "no_markers_in_telemetry"),
    ),
    "E7-10": CaseExpectation(
        case_id="E7-10",
        title="迁移恢复/隔离备份恢复/配置与 key/许可门",
        operations=("待 P0-6 恢复/发布门就绪后执行",),
        blocked_by="P0-6",
        invariants=(
            "restore_replays_suppression",
            "rpo_rto_measured",
            "old_key_rejected_new_key_works",
            "license_cleared",
        ),
    ),
}
