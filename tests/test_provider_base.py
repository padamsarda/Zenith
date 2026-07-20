"""Tests for the AssistantProvider contract and its dataclasses."""

from __future__ import annotations

import dataclasses

import pytest

from runtime.capabilities.catalog import CapabilityCatalog
from runtime.providers.base import (
    AssistantProvider,
    AssistantTurn,
    ToolCall,
    TurnBrief,
)
from shared.utils.uuid_utils import generate_id


def test_provider_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        AssistantProvider()  # type: ignore[abstract]


def test_tool_call_generates_unique_call_ids() -> None:
    assert ToolCall(tool_id="clock").call_id != ToolCall(tool_id="clock").call_id


def test_tool_call_arguments_default_to_empty_dict() -> None:
    assert ToolCall(tool_id="clock").arguments == {}


def test_tool_calls_do_not_share_default_arguments() -> None:
    first = ToolCall(tool_id="clock")
    second = ToolCall(tool_id="clock")
    first.arguments["key"] = "value"

    assert second.arguments == {}


def test_tool_call_is_frozen() -> None:
    call = ToolCall(tool_id="clock")

    with pytest.raises(dataclasses.FrozenInstanceError):
        call.tool_id = "changed"  # type: ignore[misc]


def test_turn_defaults_to_no_text_and_no_calls() -> None:
    turn = AssistantTurn()

    assert turn.text is None
    assert turn.tool_calls == ()


def test_turn_is_frozen() -> None:
    turn = AssistantTurn(text="hello")

    with pytest.raises(dataclasses.FrozenInstanceError):
        turn.text = "changed"  # type: ignore[misc]


def test_brief_defaults_to_an_empty_catalog() -> None:
    brief = TurnBrief(conversation_id=generate_id(), messages=())

    assert brief.catalog == CapabilityCatalog(tools=(), skills=())
    assert brief.instructions is None
    assert brief.metadata == {}


def test_briefs_do_not_share_default_metadata() -> None:
    first = TurnBrief(conversation_id=generate_id(), messages=())
    second = TurnBrief(conversation_id=generate_id(), messages=())
    first.metadata["key"] = "value"

    assert second.metadata == {}


def test_brief_is_frozen() -> None:
    brief = TurnBrief(conversation_id=generate_id(), messages=())

    with pytest.raises(dataclasses.FrozenInstanceError):
        brief.instructions = "changed"  # type: ignore[misc]
