"""Tests for ReflectionService: the three levels and when each fires."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone

import pytest

from configs.config import Config
from runtime.context import ApplicationContext
from runtime.memory.memory import Memory
from runtime.reflection.events import ReflectionSkipped
from runtime.reflection.reflection import Reflection, ReflectionKind
from runtime.reflection.reflector import Reflector
from runtime.reflection.service import ReflectionService
from shared.events.event import Event
from shared.utils.uuid_utils import generate_id

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


class StubReflector(Reflector):
    """A `Reflector` that returns a fixed answer and records what it saw.

    The whole reflection layer is testable without a model precisely
    because `Reflector` is an ABC over "memories in, text out".
    """

    def __init__(self, *, answer: str | None = "an insight") -> None:
        self.answer = answer
        self.calls: list[tuple[tuple[Memory, ...], str]] = []

    def reflect(self, memories, instructions, *, now=None):  # type: ignore[no-untyped-def]
        self.calls.append((tuple(memories), instructions))
        return self.answer

    @property
    def model(self) -> str:
        return "stub"


def make_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.reflection"))


def remember(
    context: ApplicationContext,
    content: str,
    *,
    conversation_id: str | None = None,
    days_ago: float = 0.0,
) -> Memory:
    moment = NOW - timedelta(days=days_ago)
    return context.memory.remember(
        Memory(
            content=content,
            occurred_at=moment,
            created_at=moment,
            last_accessed_at=moment,
            metadata={"conversation_id": conversation_id} if conversation_id else {},
        ),
        context,
    )


# --- level one: session ----------------------------------------------------------------


def test_session_reflection_summarizes_a_substantial_conversation() -> None:
    context = make_context()
    conversation_id = generate_id()
    for index in range(4):
        remember(context, f"a substantive thing {index}", conversation_id=str(conversation_id))
    service = ReflectionService(StubReflector(answer="they worked on the CubeSat"))

    reflection = service.reflect_on_session(conversation_id, context, now=NOW)

    assert reflection is not None
    assert reflection.kind is ReflectionKind.SESSION
    assert reflection.content == "they worked on the CubeSat"


def test_a_thin_conversation_is_not_reflected_on() -> None:
    # "Meaningful conversations, not every chat."
    context = make_context()
    conversation_id = generate_id()
    remember(context, "one thing only", conversation_id=str(conversation_id))
    reflector = StubReflector()
    service = ReflectionService(reflector)

    assert service.reflect_on_session(conversation_id, context, now=NOW) is None
    assert reflector.calls == []


def test_skipping_emits_an_event() -> None:
    # "Nothing happened" and "nothing was worth reflecting on" differ.
    context = make_context()
    received: list[Event] = []
    context.events.subscribe(ReflectionSkipped, received.append)

    ReflectionService(StubReflector()).reflect_on_session(generate_id(), context, now=NOW)

    assert len(received) == 1
    assert received[0].payload["kind"] == "SESSION"


def test_session_reflection_reads_only_that_conversation() -> None:
    context = make_context()
    mine, theirs = generate_id(), generate_id()
    for index in range(3):
        remember(context, f"mine {index}", conversation_id=str(mine))
    for index in range(3):
        remember(context, f"theirs {index}", conversation_id=str(theirs))
    reflector = StubReflector()

    ReflectionService(reflector).reflect_on_session(mine, context, now=NOW)

    seen = {memory.content for memory in reflector.calls[0][0]}
    assert seen == {"mine 0", "mine 1", "mine 2"}


def test_session_provenance_records_the_memories_used() -> None:
    context = make_context()
    conversation_id = generate_id()
    stored = [
        remember(context, f"thing {index}", conversation_id=str(conversation_id))
        for index in range(3)
    ]

    reflection = ReflectionService(StubReflector()).reflect_on_session(
        conversation_id, context, now=NOW
    )

    assert reflection is not None
    assert set(reflection.source_memory_ids) == {memory.memory_id for memory in stored}


def test_a_reflector_finding_nothing_stores_nothing() -> None:
    context = make_context()
    conversation_id = generate_id()
    for index in range(4):
        remember(context, f"thing {index}", conversation_id=str(conversation_id))

    reflection = ReflectionService(StubReflector(answer=None)).reflect_on_session(
        conversation_id, context, now=NOW
    )

    assert reflection is None
    assert context.reflections.list() == []


def test_on_conversation_archived_never_raises() -> None:
    # Archiving must succeed whether or not reflection does.
    class ExplodingReflector(StubReflector):
        def reflect(self, memories, instructions, *, now=None):  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    context = make_context()
    conversation_id = generate_id()
    for index in range(4):
        remember(context, f"thing {index}", conversation_id=str(conversation_id))

    ReflectionService(ExplodingReflector()).on_conversation_archived(conversation_id, context)


# --- level two: deep ----------------------------------------------------------------


def stock_memories(context: ApplicationContext, count: int = 20) -> None:
    for index in range(count):
        remember(context, f"accumulated memory number {index}", days_ago=index * 0.5)


def test_deep_reflection_is_due_when_none_has_run() -> None:
    assert ReflectionService(StubReflector()).is_deep_reflection_due(make_context(), now=NOW)


def test_deep_reflection_synthesizes_across_everything() -> None:
    context = make_context()
    stock_memories(context)

    reflection = ReflectionService(StubReflector(answer="a pattern")).reflect_deeply(
        context, now=NOW
    )

    assert reflection is not None
    assert reflection.kind is ReflectionKind.DEEP
    assert reflection.generation == 1


def test_deep_reflection_is_not_due_again_immediately() -> None:
    context = make_context()
    stock_memories(context)
    service = ReflectionService(StubReflector())
    service.reflect_deeply(context, now=NOW)

    assert service.is_deep_reflection_due(context, now=NOW + timedelta(hours=1)) is False
    assert service.reflect_deeply(context, now=NOW + timedelta(hours=1)) is None


def test_deep_reflection_is_due_again_after_the_interval() -> None:
    context = make_context()
    stock_memories(context)
    service = ReflectionService(StubReflector(), deep_interval_hours=24.0)
    service.reflect_deeply(context, now=NOW)

    assert service.is_deep_reflection_due(context, now=NOW + timedelta(hours=25))


def test_force_overrides_the_schedule() -> None:
    context = make_context()
    stock_memories(context)
    service = ReflectionService(StubReflector())
    service.reflect_deeply(context, now=NOW)

    assert service.reflect_deeply(context, force=True, now=NOW) is not None


def test_too_little_material_produces_no_deep_reflection() -> None:
    # A "pattern" across three data points is manufactured, not found.
    context = make_context()
    stock_memories(context, count=3)
    reflector = StubReflector()

    assert ReflectionService(reflector).reflect_deeply(context, now=NOW) is None
    assert reflector.calls == []


def test_successive_deep_reflections_increment_generation() -> None:
    context = make_context()
    stock_memories(context)
    service = ReflectionService(StubReflector(), deep_interval_hours=1.0)

    first = service.reflect_deeply(context, now=NOW)
    second = service.reflect_deeply(context, now=NOW + timedelta(hours=2))

    assert first is not None and second is not None
    assert (first.generation, second.generation) == (1, 2)


def test_a_new_generation_supersedes_the_previous_without_deleting_it() -> None:
    context = make_context()
    stock_memories(context)
    service = ReflectionService(StubReflector(), deep_interval_hours=1.0)
    first = service.reflect_deeply(context, now=NOW)

    second = service.reflect_deeply(context, now=NOW + timedelta(hours=2))

    assert first is not None and second is not None
    assert second.supersedes == first.reflection_id
    assert len(context.reflections.list(kind=ReflectionKind.DEEP)) == 2


# --- level three: on demand ----------------------------------------------------------------


def test_on_demand_reflection_answers_a_question() -> None:
    context = make_context()
    stock_memories(context, count=5)

    reflection = ReflectionService(StubReflector(answer="here is what I see")).reflect_on_demand(
        "what patterns do you see", context, now=NOW
    )

    assert reflection is not None
    assert reflection.kind is ReflectionKind.ON_DEMAND
    assert reflection.content == "here is what I see"


def test_on_demand_records_the_question_asked() -> None:
    context = make_context()
    stock_memories(context, count=5)

    reflection = ReflectionService(StubReflector()).reflect_on_demand(
        "what should I focus on next", context, now=NOW
    )

    assert reflection is not None
    assert reflection.metadata["question"] == "what should I focus on next"


def test_on_demand_question_reaches_the_reflector_instructions() -> None:
    context = make_context()
    stock_memories(context, count=5)
    reflector = StubReflector()

    ReflectionService(reflector).reflect_on_demand(
        "what have you learned about me", context, now=NOW
    )

    assert "what have you learned about me" in reflector.calls[0][1]


def test_on_demand_falls_back_to_recent_memories_when_nothing_matches() -> None:
    # Broad questions ("what patterns do you see") share no words with
    # any specific memory, and must not therefore read nothing.
    context = make_context()
    remember(context, "the CubeSat battery is an 18650 lithium pack")
    reflector = StubReflector()

    ReflectionService(reflector).reflect_on_demand(
        "zzz nonmatching query zzz", context, now=NOW
    )

    assert len(reflector.calls[0][0]) == 1


def test_on_demand_with_nothing_remembered_returns_none() -> None:
    reflection = ReflectionService(StubReflector()).reflect_on_demand(
        "what have you learned", make_context(), now=NOW
    )

    assert reflection is None


# --- provenance and immutability ----------------------------------------------------------------


def test_reflection_never_modifies_the_memories_it_reads() -> None:
    # The load-bearing guarantee: reflections are a layer above memory,
    # not a rewriting of it.
    context = make_context()
    stock_memories(context)
    before = {memory.memory_id: memory for memory in context.memory.list()}

    ReflectionService(StubReflector()).reflect_deeply(context, now=NOW)

    after = {memory.memory_id: memory for memory in context.memory.list()}
    assert after == before


def test_every_reflection_records_its_model() -> None:
    context = make_context()
    stock_memories(context)

    reflection = ReflectionService(StubReflector()).reflect_deeply(context, now=NOW)

    assert reflection is not None and reflection.model == "stub"


@pytest.mark.parametrize("count", [15, 40])
def test_deep_provenance_covers_every_memory_read(count: int) -> None:
    context = make_context()
    stock_memories(context, count=count)

    reflection = ReflectionService(StubReflector()).reflect_deeply(context, now=NOW)

    assert reflection is not None
    assert reflection.source_count == count
