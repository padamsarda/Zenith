"""Tests for ReflectionTool."""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import uuid4

import pytest

from configs.config import Config
from runtime.commands.context import CommandContext
from runtime.context import ApplicationContext
from runtime.exceptions import ToolExecutionError
from runtime.memory.memory import Memory
from runtime.reflection.reflection import Reflection, ReflectionKind
from runtime.reflection.service import ReflectionService
from runtime.tools.reflection_tool import ReflectionTool
from shared.utils.time_utils import utc_now
from tests.test_reflection_service import StubReflector


def make_context() -> CommandContext:
    app_context = ApplicationContext(
        config=Config(), logger=logging.getLogger("test.reflection_tool")
    )
    return CommandContext(application_context=app_context, command_id=uuid4())


def make_tool(*, answer: str | None = "an insight") -> ReflectionTool:
    return ReflectionTool(ReflectionService(StubReflector(answer=answer)))


def stock(context: CommandContext, count: int = 5) -> None:
    now = utc_now()
    for index in range(count):
        moment = now - timedelta(days=index)
        context.application_context.memory.remember(
            Memory(
                content=f"accumulated memory {index}",
                occurred_at=moment,
                created_at=moment,
                last_accessed_at=moment,
            ),
            context.application_context,
        )


# --- identity ----------------------------------------------------------------


def test_tool_identity() -> None:
    tool = make_tool()

    assert tool.tool_id == "reflection"
    assert tool.name == "Reflection"
    assert {parameter.name for parameter in tool.parameters} == {
        "operation",
        "question",
        "kind",
        "limit",
    }


# --- reflect ----------------------------------------------------------------


def test_reflect_answers_a_question() -> None:
    context = make_context()
    stock(context)

    result = make_tool(answer="you focus on CubeSat power").invoke(
        context, {"operation": "reflect", "question": "what patterns do you see"}
    )

    assert "you focus on CubeSat power" in str(result)


def test_reflect_reports_how_many_memories_it_drew_on() -> None:
    context = make_context()
    stock(context, count=4)

    result = make_tool().invoke(
        context, {"operation": "reflect", "question": "what have you learned"}
    )

    assert "4 memories" in str(result)


def test_reflect_stores_the_reflection() -> None:
    context = make_context()
    stock(context)

    make_tool().invoke(context, {"operation": "reflect", "question": "what patterns"})

    stored = context.application_context.reflections.list()
    assert len(stored) == 1
    assert stored[0].kind is ReflectionKind.ON_DEMAND


def test_reflect_with_nothing_remembered_says_so() -> None:
    result = make_tool().invoke(
        make_context(), {"operation": "reflect", "question": "what have you learned"}
    )

    assert "not enough" in str(result).lower()


def test_reflect_requires_a_question() -> None:
    with pytest.raises(ToolExecutionError):
        make_tool().invoke(make_context(), {"operation": "reflect"})


# --- list ----------------------------------------------------------------


def test_list_returns_stored_reflections() -> None:
    context = make_context()
    context.application_context.reflections.add(
        Reflection(content="a past conclusion", kind=ReflectionKind.DEEP),
        context.application_context,
    )

    result = make_tool().invoke(context, {"operation": "list"})

    assert "a past conclusion" in str(result)


def test_list_makes_no_model_call() -> None:
    # The cheap path: reading conclusions must not pay for new ones.
    context = make_context()
    context.application_context.reflections.add(
        Reflection(content="a past conclusion"), context.application_context
    )
    reflector = StubReflector()

    ReflectionTool(ReflectionService(reflector)).invoke(context, {"operation": "list"})

    assert reflector.calls == []


def test_list_filters_by_kind() -> None:
    context = make_context()
    for kind in (ReflectionKind.SESSION, ReflectionKind.DEEP):
        context.application_context.reflections.add(
            Reflection(content=f"{kind.name} content", kind=kind), context.application_context
        )

    result = make_tool().invoke(context, {"operation": "list", "kind": "deep"})

    assert "DEEP content" in str(result)
    assert "SESSION content" not in str(result)


def test_list_respects_the_limit() -> None:
    context = make_context()
    for index in range(5):
        context.application_context.reflections.add(
            Reflection(content=f"conclusion {index}"), context.application_context
        )

    result = make_tool().invoke(context, {"operation": "list", "limit": 2})

    assert len(result.entries) == 2


def test_list_with_nothing_stored_says_so() -> None:
    result = make_tool().invoke(make_context(), {"operation": "list"})

    assert "nothing has been concluded" in str(result).lower()


def test_list_rejects_an_unknown_kind() -> None:
    with pytest.raises(ToolExecutionError):
        make_tool().invoke(make_context(), {"operation": "list", "kind": "nonsense"})


def test_list_rejects_a_bad_limit() -> None:
    with pytest.raises(ToolExecutionError):
        make_tool().invoke(make_context(), {"operation": "list", "limit": 0})


# --- unknown operation ----------------------------------------------------------------


def test_unknown_operation_raises() -> None:
    with pytest.raises(ToolExecutionError):
        make_tool().invoke(make_context(), {"operation": "ponder"})
