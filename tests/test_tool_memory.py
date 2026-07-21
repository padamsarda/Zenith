"""Tests for MemoryTool."""

from __future__ import annotations

import logging
from uuid import uuid4

import pytest

from configs.config import Config
from runtime.commands.context import CommandContext
from runtime.context import ApplicationContext
from runtime.exceptions import ToolExecutionError
from runtime.memory.memory import MAX_IMPORTANCE, Memory, MemoryKind
from runtime.tools.memory_tool import MemoryTool


def make_context() -> CommandContext:
    app_context = ApplicationContext(config=Config(), logger=logging.getLogger("test.memory_tool"))
    return CommandContext(application_context=app_context, command_id=uuid4())


# --- identity ----------------------------------------------------------------


def test_tool_identity() -> None:
    tool = MemoryTool()

    assert tool.tool_id == "memory"
    assert tool.name == "Memory"
    assert {parameter.name for parameter in tool.parameters} >= {
        "operation",
        "content",
        "kind",
        "importance",
        "pinned",
        "memory_id",
    }


# --- remember ----------------------------------------------------------------


def test_remember_stores_a_pinned_memory_by_default() -> None:
    context = make_context()
    tool = MemoryTool()

    result = tool.invoke(
        context, {"operation": "remember", "content": "My student ID is f20250775"}
    )

    stored = context.application_context.memory.list()
    assert len(stored) == 1
    assert stored[0].pinned is True
    assert stored[0].importance == MAX_IMPORTANCE
    assert stored[0].source == "tool"
    assert "f20250775" in str(result)


def test_remember_accepts_an_explicit_kind() -> None:
    context = make_context()

    MemoryTool().invoke(
        context,
        {"operation": "remember", "content": "I prefer metric units", "kind": "preference"},
    )

    assert context.application_context.memory.list()[0].kind is MemoryKind.PREFERENCE


def test_remember_rejects_an_unknown_kind() -> None:
    with pytest.raises(ToolExecutionError):
        MemoryTool().invoke(
            make_context(), {"operation": "remember", "content": "x y z", "kind": "nonsense"}
        )


def test_remember_rejects_out_of_range_importance() -> None:
    with pytest.raises(ToolExecutionError):
        MemoryTool().invoke(
            make_context(),
            {"operation": "remember", "content": "something", "importance": 42},
        )


def test_remember_requires_content() -> None:
    with pytest.raises(ToolExecutionError):
        MemoryTool().invoke(make_context(), {"operation": "remember"})


# --- search ----------------------------------------------------------------


def test_search_finds_a_stored_memory() -> None:
    context = make_context()
    tool = MemoryTool()
    tool.invoke(
        context, {"operation": "remember", "content": "The CubeSat battery is lithium"}
    )

    result = tool.invoke(context, {"operation": "search", "content": "cubesat battery"})

    assert len(result.entries) == 1
    assert "lithium" in result.entries[0]


def test_search_with_no_matches_says_so() -> None:
    result = MemoryTool().invoke(
        make_context(), {"operation": "search", "content": "kubernetes"}
    )

    assert result.entries == ()
    assert "nothing remembered" in str(result)


def test_search_entries_include_the_id_for_forgetting() -> None:
    context = make_context()
    tool = MemoryTool()
    tool.invoke(context, {"operation": "remember", "content": "The battery is lithium"})
    stored = context.application_context.memory.list()[0]

    result = tool.invoke(context, {"operation": "search", "content": "battery"})

    assert str(stored.memory_id) in result.entries[0]


# --- forget ----------------------------------------------------------------


def test_forget_removes_the_memory() -> None:
    context = make_context()
    memory = context.application_context.memory.remember(
        Memory(content="wrong fact"), context.application_context
    )

    MemoryTool().invoke(
        context, {"operation": "forget", "memory_id": str(memory.memory_id)}
    )

    assert not context.application_context.memory.has(memory.memory_id)


def test_forget_unknown_id_raises() -> None:
    with pytest.raises(ToolExecutionError):
        MemoryTool().invoke(
            make_context(), {"operation": "forget", "memory_id": str(uuid4())}
        )


def test_forget_malformed_id_raises() -> None:
    with pytest.raises(ToolExecutionError):
        MemoryTool().invoke(make_context(), {"operation": "forget", "memory_id": "not-a-uuid"})


# --- unknown operation ----------------------------------------------------------------


def test_unknown_operation_raises() -> None:
    with pytest.raises(ToolExecutionError):
        MemoryTool().invoke(make_context(), {"operation": "summarize"})
