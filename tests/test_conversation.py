"""Tests for the Conversation class."""

from __future__ import annotations

import pytest

from runtime.conversation.conversation import Conversation
from runtime.conversation.message import Message, MessageRole
from runtime.conversation.state import ConversationState
from runtime.exceptions import ConversationValidationError


def test_new_conversation_is_active() -> None:
    conversation = Conversation()

    assert conversation.state is ConversationState.ACTIVE


def test_new_conversation_has_no_messages() -> None:
    conversation = Conversation()

    assert conversation.messages == ()


def test_conversations_get_unique_ids() -> None:
    assert Conversation().conversation_id != Conversation().conversation_id


def test_conversation_carries_title_and_metadata() -> None:
    conversation = Conversation(title="Chat", metadata={"channel": "console"})

    assert conversation.title == "Chat"
    assert conversation.metadata == {"channel": "console"}


def test_title_defaults_to_none() -> None:
    assert Conversation().title is None


def test_created_at_is_timezone_aware() -> None:
    assert Conversation().created_at.tzinfo is not None


def test_append_adds_message_in_order() -> None:
    conversation = Conversation()
    first = Message(role=MessageRole.USER, content="hello")
    second = Message(role=MessageRole.ASSISTANT, content="hi")
    conversation.append(first)
    conversation.append(second)

    assert conversation.messages == (first, second)


def test_messages_returns_a_snapshot() -> None:
    conversation = Conversation()
    conversation.append(Message(role=MessageRole.USER, content="hello"))
    snapshot = conversation.messages
    conversation.append(Message(role=MessageRole.ASSISTANT, content="hi"))

    assert len(snapshot) == 1


def test_append_validates_the_message() -> None:
    conversation = Conversation()

    with pytest.raises(ConversationValidationError):
        conversation.append(Message(role=MessageRole.USER, content="  "))


def test_append_on_archived_conversation_raises() -> None:
    conversation = Conversation()
    conversation.transition_to(ConversationState.ARCHIVED)

    with pytest.raises(ConversationValidationError):
        conversation.append(Message(role=MessageRole.USER, content="hello"))


def test_transition_to_archived_succeeds() -> None:
    conversation = Conversation()
    conversation.transition_to(ConversationState.ARCHIVED)

    assert conversation.state is ConversationState.ARCHIVED


def test_invalid_transition_raises_and_preserves_state() -> None:
    conversation = Conversation()

    with pytest.raises(ConversationValidationError):
        conversation.transition_to(ConversationState.ACTIVE)
    assert conversation.state is ConversationState.ACTIVE


def test_state_cannot_be_assigned_directly() -> None:
    conversation = Conversation()

    with pytest.raises(AttributeError):
        conversation.state = ConversationState.ARCHIVED  # type: ignore[misc]
