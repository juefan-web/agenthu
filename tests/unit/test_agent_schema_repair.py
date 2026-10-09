"""Schema-repair retry regression set (audit defect 1, slice alpha).

The repair path used to call the async provider without awaiting: the
coroutine object then failed ``model_validate_json`` inside a broad
``except Exception``, so the "one repair retry" silently never ran and
CPython raised a "never awaited" RuntimeWarning per attempt. The
``filterwarnings("error")`` marks below turn any such dangling coroutine
into a test failure.
"""

from __future__ import annotations

import pytest

from backend.services.agent_runner import _validate_arguments
from backend.services.tool_registry import get_tool


class RepairProvider:
    """Async generate() matching the ModelProvider protocol shape."""

    name = "repair-fake"
    model_name = "repair-fake-model"

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[str] = []

    async def generate(self, input_text: str, instructions: str | None = None) -> str:
        self.calls.append(input_text)
        return self.reply


def _task_create_tool():
    tool = get_tool("task.create")
    assert tool is not None
    return tool


@pytest.mark.filterwarnings("error::RuntimeWarning")
async def test_repair_heal_returns_repaired_args_and_actually_awaits() -> None:
    provider = RepairProvider('{"title": "修复后的任务"}')
    args, schema_error = await _validate_arguments(_task_create_tool(), '{"title": ', provider)
    assert schema_error == {"repaired_args": args}
    assert args.title == "修复后的任务"
    assert len(provider.calls) == 1
    assert "task.create" in provider.calls[0]


@pytest.mark.filterwarnings("error::RuntimeWarning")
async def test_repair_failure_returns_repaired_false_without_raising() -> None:
    provider = RepairProvider("still not json")
    args, schema_error = await _validate_arguments(_task_create_tool(), "not json at all", provider)
    assert args is None
    assert schema_error == {"repaired": False}
    assert len(provider.calls) == 1


async def test_valid_arguments_skip_the_repair_entirely() -> None:
    provider = RepairProvider('{"title": "never used"}')
    args, schema_error = await _validate_arguments(
        _task_create_tool(), '{"title": "直接通过"}', provider
    )
    assert schema_error is None
    assert args.title == "直接通过"
    assert provider.calls == []


async def test_missing_provider_fails_closed_without_any_repair_call() -> None:
    args, schema_error = await _validate_arguments(_task_create_tool(), "not json at all", None)
    assert args is None
    assert schema_error == {"repaired": False}


@pytest.mark.filterwarnings("error::RuntimeWarning")
async def test_provider_without_generate_fails_closed() -> None:
    class BareProvider:
        name = "bare"

    args, schema_error = await _validate_arguments(
        _task_create_tool(), "not json at all", BareProvider()
    )
    assert args is None
    assert schema_error == {"repaired": False}
