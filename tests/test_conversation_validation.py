"""Tests for the conversation validation guard functions."""

from __future__ import annotations

import pytest

from runtime.conversation.conversation import Conversation
from runtime.conversation.message import Message, MessageRole
from runtime.conversation.state import ConversationState
from runtime.conversation.validation import (
    validate_conversation_active,
    validate_message,
    validate_message_content,
    validate_message_metadata,
    validate_state_transition,
)
from runtime.exceptions import ConversationValidationError


# --- validate_state_transition ------------------------------------------


def test_active_to_archived_is_valid() -> None:
    validate_state_transition(ConversationState.ACTIVE, ConversationState.ARCHIVED)


def test_archived_to_active_raises() -> None:
    with pytest.raises(ConversationValidationError):
        validate_state_transition(ConversationState.ARCHIVED, ConversationState.ACTIVE)


def test_active_to_active_raises() -> None:
    with pytest.raises(ConversationValidationError):
        validate_state_transition(ConversationState.ACTIVE, ConversationState.ACTIVE)


def test_archived_to_archived_raises() -> None:
    with pytest.raises(ConversationValidationError):
        validate_state_transition(ConversationState.ARCHIVED, ConversationState.ARCHIVED)


# --- validate_message_content -------------------------------------------


def test_plain_text_content_is_valid() -> None:
    validate_message_content("hello")


def test_padded_content_is_valid() -> None:
    validate_message_content("multi-line output\n")


def test_empty_content_raises() -> None:
    with pytest.raises(ConversationValidationError):
        validate_message_content("")


def test_whitespace_only_content_raises() -> None:
    with pytest.raises(ConversationValidationError):
        validate_message_content("   \n")


def test_non_string_content_raises() -> None:
    with pytest.raises(ConversationValidationError):
        validate_message_content(42)


# --- validate_message_metadata ------------------------------------------


def test_string_keyed_metadata_is_valid() -> None:
    validate_message_metadata({"request_id": "abc"})


def test_non_dict_metadata_raises() -> None:
    with pytest.raises(ConversationValidationError):
        validate_message_metadata("bad")  # type: ignore[arg-type]


def test_non_string_metadata_key_raises() -> None:
    with pytest.raises(ConversationValidationError):
        validate_message_metadata({1: "value"})  # type: ignore[dict-item]


# --- validate_message ---------------------------------------------------


def test_valid_message_passes() -> None:
    validate_message(Message(role=MessageRole.USER, content="hello"))


def test_message_with_non_role_raises() -> None:
    message = Message(role="user", content="hello")  # type: ignore[arg-type]

    with pytest.raises(ConversationValidationError):
        validate_message(message)


def test_message_with_blank_content_raises() -> None:
    message = Message(role=MessageRole.USER, content="  ")

    with pytest.raises(ConversationValidationError):
        validate_message(message)


# --- validate_conversation_active ---------------------------------------


def test_active_conversation_passes() -> None:
    validate_conversation_active(Conversation())


def test_archived_conversation_raises() -> None:
    conversation = Conversation()
    conversation.transition_to(ConversationState.ARCHIVED)

    with pytest.raises(ConversationValidationError):
        validate_conversation_active(conversation)
