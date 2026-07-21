"""Tests for MemoryRecaller and brief rendering."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from configs.config import Config
from runtime.context import ApplicationContext
from runtime.memory.events import MemoriesRecalled
from runtime.memory.memory import Memory, MemoryKind
from runtime.memory.recall import MemoryRecaller, describe_age, render_memories
from runtime.memory.store import MemoryStore
from shared.events.event import Event

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def make_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.recall"))


def remember(
    context: ApplicationContext, content: str, *, days_ago: float = 0.0, **kwargs
) -> Memory:
    moment = NOW - timedelta(days=days_ago)
    memory = Memory(
        content=content,
        occurred_at=moment,
        created_at=moment,
        last_accessed_at=moment,
        **kwargs,
    )
    return context.memory.remember(memory, context)


# --- recall ----------------------------------------------------------------


def test_recall_finds_relevant_memory() -> None:
    context = make_context()
    remember(context, "The CubeSat battery is an 18650 lithium pack")
    remember(context, "I prefer dark mode in editors")

    recalled = MemoryRecaller().recall("what battery does the cubesat use", context, now=NOW)

    assert len(recalled) == 1
    assert "18650" in recalled[0].memory.content


def test_recall_narrows_by_time_expression() -> None:
    context = make_context()
    remember(context, "CubeSat battery discussion", days_ago=1)
    remember(context, "CubeSat battery discussion", days_ago=40)

    recalled = MemoryRecaller().recall("what did we say about the battery yesterday", context, now=NOW)

    assert len(recalled) == 1
    assert recalled[0].memory.occurred_at == NOW - timedelta(days=1)


def test_recall_with_only_a_time_expression_returns_that_day() -> None:
    context = make_context()
    remember(context, "Worked on the power budget", days_ago=1)
    remember(context, "Worked on the antenna", days_ago=30)

    recalled = MemoryRecaller().recall("what was I doing yesterday", context, now=NOW)

    assert [scored.memory.content for scored in recalled] == ["Worked on the power budget"]


def test_recall_respects_the_limit() -> None:
    context = make_context()
    for index in range(10):
        remember(context, f"CubeSat note {index}")

    recalled = MemoryRecaller(recall_limit=3).recall("cubesat note", context, now=NOW)

    assert len(recalled) == 3


def test_recall_with_nothing_stored_returns_nothing() -> None:
    assert MemoryRecaller().recall("anything", make_context(), now=NOW) == ()


def test_recall_marks_memories_as_accessed() -> None:
    context = make_context()
    memory = remember(context, "The CubeSat battery is lithium")

    MemoryRecaller().recall("cubesat battery", context, now=NOW)

    assert context.memory.get(memory.memory_id).access_count == 1


def test_recall_emits_event() -> None:
    context = make_context()
    remember(context, "The CubeSat battery is lithium")
    received: list[Event] = []
    context.events.subscribe(MemoriesRecalled, received.append)

    MemoryRecaller().recall("cubesat battery", context, now=NOW)

    assert len(received) == 1
    assert received[0].payload["count"] == 1


def test_recall_never_raises_when_the_store_fails() -> None:
    # A broken memory subsystem must degrade to an assistant with no
    # memory, never a failed request.
    class BrokenStore(MemoryStore):
        def remember(self, memory, application_context):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        def get(self, memory_id):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        def has(self, memory_id):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        def forget(self, memory_id, application_context):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        def search(self, query, *, window=None, limit=50):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        def touch(self, memories, application_context):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

        def list(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    context = make_context()
    context.memory = BrokenStore()

    assert MemoryRecaller().recall("anything", context, now=NOW) == ()


def test_pinned_memory_survives_a_flood_of_recent_ones() -> None:
    # The end-to-end version of "it remembered what I told it to".
    context = make_context()
    remember(
        context,
        "My student ID is f20250775",
        days_ago=200,
        pinned=True,
        importance=10,
        kind=MemoryKind.FACT,
    )
    for index in range(20):
        remember(context, f"Some routine note about student work {index}", days_ago=0.1)

    recalled = MemoryRecaller().recall("what is my student ID", context, now=NOW)

    assert any("f20250775" in scored.memory.content for scored in recalled)


# --- rendering ----------------------------------------------------------------


def test_render_returns_none_with_no_memories() -> None:
    assert render_memories((), NOW) is None


def test_render_includes_content_and_age() -> None:
    context = make_context()
    remember(context, "The CubeSat battery is lithium", days_ago=1)
    recalled = MemoryRecaller().recall("cubesat battery", context, now=NOW)

    rendered = render_memories(recalled, NOW)

    assert rendered is not None
    assert "The CubeSat battery is lithium" in rendered
    assert "yesterday" in rendered


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (1, "yesterday"),
        (3, "3 days ago"),
        (10, "1 week ago"),
        (20, "2 weeks ago"),
        (60, "2 months ago"),
        (400, "1 year ago"),
    ],
)
def test_describe_age(days: int, expected: str) -> None:
    assert expected in describe_age(NOW - timedelta(days=days), NOW)


def test_describe_age_handles_minutes() -> None:
    assert describe_age(NOW - timedelta(minutes=5), NOW) == "minutes ago"
