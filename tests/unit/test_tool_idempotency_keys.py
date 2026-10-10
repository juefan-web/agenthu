"""External review #12: tool idempotency keys must be process-stable.

``hash()`` is PYTHONHASHSEED-randomized, so the two content-derived keys
(memory.write / notify.push) produced different values in every process —
an idempotent replay after a restart or on another worker never matched.
The keys are now sha256-derived; these pins assert the exact formula (a
hash()-based implementation cannot reproduce it regardless of seed),
equality for equal inputs and separation for different ones."""

from __future__ import annotations

import hashlib

from backend.models.enums import MemoryKind
from backend.services.agent_tools import MemoryWriteArgs, NotifyPushArgs
from backend.services.tool_registry import get_tool


def test_memory_write_key_is_sha256_of_content() -> None:
    tool = get_tool("memory.write")
    assert tool is not None and tool.idempotency_key is not None
    args = MemoryWriteArgs(content="该生在滤波器作业平均用时 40 分钟", kind=MemoryKind.FACT)

    digest = hashlib.sha256("该生在滤波器作业平均用时 40 分钟".encode()).hexdigest()[:16]
    assert tool.idempotency_key(args) == f"memory.write:{digest}:fact"

    twin = MemoryWriteArgs(content="该生在滤波器作业平均用时 40 分钟", kind=MemoryKind.FACT)
    assert tool.idempotency_key(twin) == tool.idempotency_key(args)
    other = MemoryWriteArgs(content="不同的内容", kind=MemoryKind.FACT)
    assert tool.idempotency_key(other) != tool.idempotency_key(args)


def test_notify_push_key_is_sha256_of_title() -> None:
    tool = get_tool("notify.push")
    assert tool is not None and tool.idempotency_key is not None
    args = NotifyPushArgs(category="replan", title="计划有变，建议重排今晚")

    digest = hashlib.sha256("计划有变，建议重排今晚".encode()).hexdigest()[:16]
    assert tool.idempotency_key(args) == f"notify.push:replan:{digest}"

    twin = NotifyPushArgs(category="replan", title="计划有变，建议重排今晚", body="详情见内")
    assert tool.idempotency_key(twin) == tool.idempotency_key(args), "body must not dilute the key"
    other_title = NotifyPushArgs(category="replan", title="另一条通知标题")
    assert tool.idempotency_key(other_title) != tool.idempotency_key(args)
