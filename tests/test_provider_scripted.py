"""Tests for the ScriptedProvider."""

from __future__ import annotations

import pytest

from runtime.exceptions import AssistantProviderError
from runtime.providers.base import AssistantTurn, ToolCall, TurnBrief
from runtime.providers.scripted import ScriptedProvider
from shared.utils.uuid_utils import generate_id


def make_brief() -> TurnBrief:
    return TurnBrief(conversation_id=generate_id(), messages=())


def test_provider_identity_defaults() -> None:
    provider = ScriptedProvider()

    assert provider.provider_id == "scripted"
    assert provider.name == "Scripted"


def test_provider_id_is_injectable() -> None:
    assert ScriptedProvider(provider_id="alt").provider_id == "alt"


def test_returns_scripted_turns_in_order() -> None:
    first = AssistantTurn(tool_calls=(ToolCall(tool_id="clock"),))
    second = AssistantTurn(text="done")
    provider = ScriptedProvider([first, second])

    assert provider.generate_turn(make_brief()) is first
    assert provider.generate_turn(make_brief()) is second


def test_records_briefs_in_order() -> None:
    provider = ScriptedProvider([AssistantTurn(text="one"), AssistantTurn(text="two")])
    first_brief = make_brief()
    second_brief = make_brief()
    provider.generate_turn(first_brief)
    provider.generate_turn(second_brief)

    assert provider.briefs == [first_brief, second_brief]


def test_exhausted_script_raises() -> None:
    provider = ScriptedProvider()

    with pytest.raises(AssistantProviderError):
        provider.generate_turn(make_brief())


def test_exhausted_script_still_records_the_brief() -> None:
    provider = ScriptedProvider()
    brief = make_brief()

    with pytest.raises(AssistantProviderError):
        provider.generate_turn(brief)
    assert provider.briefs == [brief]


def test_add_turn_extends_the_script() -> None:
    provider = ScriptedProvider()
    provider.add_turn(AssistantTurn(text="added"))

    assert provider.generate_turn(make_brief()).text == "added"
