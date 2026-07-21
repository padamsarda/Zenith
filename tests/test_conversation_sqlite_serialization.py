"""Tests for conversation domain-object <-> database-row conversion."""

from __future__ import annotations

import sqlite3
from typing import Any

from runtime.conversation.conversation import Conversation
from runtime.conversation.message import Message, MessageRole
from runtime.conversation.sqlite.serialization import (
    conversation_from_row,
    conversation_to_row,
    message_from_row,
    message_to_row,
)
from runtime.conversation.state import ConversationState


def as_row(values: dict[str, Any]) -> sqlite3.Row:
    """Materialize a dict as a real sqlite3.Row, as the store would see it."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    columns = ", ".join(values)
    placeholders = ", ".join(f":{column}" for column in values)
    connection.execute(f"CREATE TABLE row_test ({columns})")
    connection.execute(f"INSERT INTO row_test ({columns}) VALUES ({placeholders})", values)
    row = connection.execute("SELECT * FROM row_test").fetchone()
    connection.close()
    return row


# --- conversations -----------------------------------------------------------


def test_conversation_round_trip_preserves_identity_and_content() -> None:
    conversation = Conversation(title="Chat", metadata={"channel": "console"})

    restored = conversation_from_row(as_row(conversation_to_row(conversation)), messages=[])

    assert restored.conversation_id == conversation.conversation_id
    assert restored.created_at == conversation.created_at
    assert restored.title == conversation.title
    assert restored.metadata == conversation.metadata
    assert restored.state == conversation.state


def test_conversation_round_trip_preserves_archived_state() -> None:
    conversation = Conversation()
    conversation.transition_to(ConversationState.ARCHIVED)

    restored = conversation_from_row(as_row(conversation_to_row(conversation)), messages=[])

    assert restored.state is ConversationState.ARCHIVED


def test_conversation_round_trip_preserves_none_title() -> None:
    conversation = Conversation(title=None)

    restored = conversation_from_row(as_row(conversation_to_row(conversation)), messages=[])

    assert restored.title is None


def test_conversation_from_row_attaches_given_messages() -> None:
    conversation = Conversation()
    message = Message(role=MessageRole.USER, content="hello")

    restored = conversation_from_row(as_row(conversation_to_row(conversation)), messages=[message])

    assert restored.messages == (message,)


# --- messages ------------------------------------------------------------


def test_message_round_trip_preserves_identity_and_content() -> None:
    conversation_id = Conversation().conversation_id
    message = Message(role=MessageRole.ASSISTANT, content="hi there", metadata={"turn": 1})

    restored = message_from_row(as_row(message_to_row(conversation_id, message)))

    assert restored.message_id == message.message_id
    assert restored.role == message.role
    assert restored.content == message.content
    assert restored.metadata == message.metadata
    assert restored.created_at == message.created_at


def test_message_to_row_carries_the_conversation_id() -> None:
    conversation_id = Conversation().conversation_id
    message = Message(role=MessageRole.TOOL, content="result")

    row = message_to_row(conversation_id, message)

    assert row["conversation_id"] == str(conversation_id)
