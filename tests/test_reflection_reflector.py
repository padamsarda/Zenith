"""Tests for ProviderReflector and reflection prompts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.exceptions import AssistantProviderError
from runtime.memory.memory import Memory, MemoryKind
from runtime.providers.base import AssistantProvider, AssistantTurn
from runtime.providers.scripted import ScriptedProvider
from runtime.reflection.prompts import (
    DEEP_INSTRUCTIONS,
    SESSION_INSTRUCTIONS,
    on_demand_instructions,
    render_memories,
)
from runtime.reflection.reflector import ProviderReflector

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def make_memories(count: int = 3) -> list[Memory]:
    return [
        Memory(
            content=f"memory {index}",
            occurred_at=NOW - timedelta(days=index),
            created_at=NOW - timedelta(days=index),
            last_accessed_at=NOW - timedelta(days=index),
        )
        for index in range(count)
    ]


class FailingProvider(AssistantProvider):
    @property
    def provider_id(self) -> str:
        return "failing"

    @property
    def name(self) -> str:
        return "Failing"

    def generate_turn(self, brief):  # type: ignore[no-untyped-def]
        raise AssistantProviderError("boom")


# --- reflecting ----------------------------------------------------------------


def test_reflect_returns_the_providers_text() -> None:
    provider = ScriptedProvider(turns=[AssistantTurn(text="they work on CubeSats")])

    result = ProviderReflector(provider).reflect(make_memories(), SESSION_INSTRUCTIONS, now=NOW)

    assert result == "they work on CubeSats"


def test_instructions_and_material_reach_the_provider() -> None:
    provider = ScriptedProvider(turns=[AssistantTurn(text="ok")])

    ProviderReflector(provider).reflect(make_memories(), DEEP_INSTRUCTIONS, now=NOW)

    brief = provider.briefs[0]
    assert brief.instructions == DEEP_INSTRUCTIONS
    assert "memory 0" in brief.messages[0].content


def test_reflection_offers_no_tools() -> None:
    # Reflection reads and concludes; it must not be able to act.
    provider = ScriptedProvider(turns=[AssistantTurn(text="ok")])

    ProviderReflector(provider).reflect(make_memories(), DEEP_INSTRUCTIONS, now=NOW)

    assert provider.briefs[0].catalog.tools == ()


def test_no_memories_means_no_call_and_no_result() -> None:
    provider = ScriptedProvider(turns=[AssistantTurn(text="should not happen")])

    assert ProviderReflector(provider).reflect([], DEEP_INSTRUCTIONS, now=NOW) is None
    assert provider.briefs == []


# --- declining to reflect ----------------------------------------------------------------


def test_the_nothing_verdict_becomes_none() -> None:
    # A reflector must be able to find nothing, or every run invents.
    provider = ScriptedProvider(turns=[AssistantTurn(text="NOTHING")])

    assert ProviderReflector(provider).reflect(make_memories(), DEEP_INSTRUCTIONS, now=NOW) is None


def test_the_nothing_verdict_is_recognized_with_trailing_text() -> None:
    provider = ScriptedProvider(
        turns=[AssistantTurn(text="NOTHING — too little to go on here.")]
    )

    assert ProviderReflector(provider).reflect(make_memories(), DEEP_INSTRUCTIONS, now=NOW) is None


def test_empty_text_becomes_none() -> None:
    provider = ScriptedProvider(turns=[AssistantTurn(text="   ")])

    assert ProviderReflector(provider).reflect(make_memories(), DEEP_INSTRUCTIONS, now=NOW) is None


def test_a_failing_provider_yields_none_rather_than_raising() -> None:
    # Reflection is derived, optional value: it must never break what it
    # was triggered by.
    result = ProviderReflector(FailingProvider()).reflect(
        make_memories(), DEEP_INSTRUCTIONS, now=NOW
    )

    assert result is None


# --- model reporting ----------------------------------------------------------------


def test_model_defaults_to_the_provider_id() -> None:
    assert ProviderReflector(ScriptedProvider(turns=[])).model == "scripted"


def test_model_can_be_overridden() -> None:
    reflector = ProviderReflector(ScriptedProvider(turns=[]), model="claude-haiku-4-5")

    assert reflector.model == "claude-haiku-4-5"


# --- rendering material ----------------------------------------------------------------


def test_rendered_material_carries_age_kind_and_importance() -> None:
    memory = Memory(
        content="the battery is lithium",
        kind=MemoryKind.DECISION,
        importance=8,
        occurred_at=NOW - timedelta(days=1),
        created_at=NOW - timedelta(days=1),
        last_accessed_at=NOW - timedelta(days=1),
    )

    rendered = render_memories([memory], NOW)

    assert "yesterday" in rendered
    assert "decision" in rendered
    assert "importance 8" in rendered
    assert "the battery is lithium" in rendered


def test_pinned_memories_are_marked() -> None:
    memory = Memory(
        content="my student ID is f20250775",
        pinned=True,
        occurred_at=NOW,
        created_at=NOW,
        last_accessed_at=NOW,
    )

    assert "[pinned]" in render_memories([memory], NOW)


def test_on_demand_instructions_carry_the_question() -> None:
    instructions = on_demand_instructions("  what should I focus on next  ")

    assert "what should I focus on next" in instructions


def test_prompts_forbid_speculation() -> None:
    # Grounding is the whole difference between reflection and invention.
    for instructions in (SESSION_INSTRUCTIONS, DEEP_INSTRUCTIONS, on_demand_instructions("x")):
        assert "speculate" in instructions.lower()
