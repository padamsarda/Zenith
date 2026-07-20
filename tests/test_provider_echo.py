"""Tests for the EchoProvider."""

from __future__ import annotations

import pytest

from runtime.conversation.message import Message, MessageRole
from runtime.exceptions import AssistantProviderError
from runtime.providers.base import TurnBrief
from runtime.providers.echo import EchoProvider
from shared.utils.uuid_utils import generate_id


def make_brief(messages: tuple[Message, ...]) -> TurnBrief:
    return TurnBrief(conversation_id=generate_id(), messages=messages)


def test_provider_identity() -> None:
    provider = EchoProvider()

    assert provider.provider_id == "echo"
    assert provider.name == "Echo"


def test_echoes_the_user_message() -> None:
    brief = make_brief((Message(role=MessageRole.USER, content="hello"),))

    turn = EchoProvider().generate_turn(brief)

    assert turn.text == "You said: hello"
    assert turn.tool_calls == ()


def test_echoes_the_most_recent_user_message() -> None:
    brief = make_brief(
        (
            Message(role=MessageRole.USER, content="first"),
            Message(role=MessageRole.ASSISTANT, content="You said: first"),
            Message(role=MessageRole.USER, content="second"),
        )
    )

    assert EchoProvider().generate_turn(brief).text == "You said: second"


def test_ignores_non_user_messages() -> None:
    brief = make_brief(
        (
            Message(role=MessageRole.USER, content="hello"),
            Message(role=MessageRole.TOOL, content="result"),
        )
    )

    assert EchoProvider().generate_turn(brief).text == "You said: hello"


def test_no_user_message_raises() -> None:
    brief = make_brief((Message(role=MessageRole.SYSTEM, content="setup"),))

    with pytest.raises(AssistantProviderError):
        EchoProvider().generate_turn(brief)
