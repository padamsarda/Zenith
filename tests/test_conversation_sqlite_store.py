"""Tests for SQLiteConversationStore."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from configs.config import Config
from runtime.context import ApplicationContext
from runtime.conversation.events import (
    ConversationArchived,
    ConversationStarted,
    MessageAppended,
)
from runtime.conversation.message import Message, MessageRole
from runtime.conversation.sqlite.store import SQLiteConversationStore
from runtime.conversation.state import ConversationState
from runtime.exceptions import ConversationNotFoundError, ConversationValidationError
from shared.events.event import Event
from shared.utils.uuid_utils import generate_id


def make_application_context() -> ApplicationContext:
    return ApplicationContext(
        config=Config(), logger=logging.getLogger("test.conversation_sqlite_store")
    )


def make_store(tmp_path: Path) -> SQLiteConversationStore:
    return SQLiteConversationStore(tmp_path / "conversations.db")


def subscribe_all(app_context: ApplicationContext) -> list[Event]:
    received: list[Event] = []
    for event_type in (ConversationStarted, ConversationArchived, MessageAppended):
        app_context.events.subscribe(event_type, received.append)
    return received


# --- same behavioral contract as InMemoryConversationStore --------------------


def test_create_returns_an_active_stored_conversation(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()

    conversation = store.create(app_context, title="Chat")

    assert conversation.state is ConversationState.ACTIVE
    assert store.get(conversation.conversation_id).conversation_id == conversation.conversation_id
    store.close()


def test_create_emits_conversation_started(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()
    received = subscribe_all(app_context)

    conversation = store.create(app_context, title="Chat")

    assert [type(event) for event in received] == [ConversationStarted]
    assert received[0].payload == {
        "conversation_id": str(conversation.conversation_id),
        "title": "Chat",
    }
    store.close()


def test_get_unknown_conversation_raises(tmp_path: Path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(ConversationNotFoundError):
        store.get(generate_id())
    store.close()


def test_has_reports_presence(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()
    conversation = store.create(app_context)

    assert store.has(conversation.conversation_id)
    assert not store.has(generate_id())
    store.close()


def test_list_returns_conversations_in_creation_order(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()
    first = store.create(app_context, title="First")
    second = store.create(app_context, title="Second")

    listed = store.list()

    assert [c.conversation_id for c in listed] == [first.conversation_id, second.conversation_id]
    store.close()


def test_append_adds_message_and_emits(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()
    conversation = store.create(app_context)
    received = subscribe_all(app_context)
    message = Message(role=MessageRole.USER, content="hello")

    store.append(conversation.conversation_id, message, app_context)

    assert store.get(conversation.conversation_id).messages == (message,)
    assert [type(event) for event in received] == [MessageAppended]
    assert received[0].payload["role"] == "USER"
    assert received[0].payload["message_id"] == str(message.message_id)
    store.close()


def test_append_to_unknown_conversation_raises(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()

    with pytest.raises(ConversationNotFoundError):
        store.append(generate_id(), Message(role=MessageRole.USER, content="hello"), app_context)
    store.close()


def test_append_invalid_message_raises_and_emits_nothing(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()
    conversation = store.create(app_context)
    received = subscribe_all(app_context)

    with pytest.raises(ConversationValidationError):
        store.append(
            conversation.conversation_id, Message(role=MessageRole.USER, content=""), app_context
        )
    assert received == []
    store.close()


def test_append_invalid_message_does_not_persist_a_row(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()
    conversation = store.create(app_context)

    with pytest.raises(ConversationValidationError):
        store.append(
            conversation.conversation_id, Message(role=MessageRole.USER, content=""), app_context
        )

    assert store.get(conversation.conversation_id).messages == ()
    store.close()


def test_archive_transitions_and_emits(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()
    conversation = store.create(app_context)
    received = subscribe_all(app_context)

    store.archive(conversation.conversation_id, app_context)

    assert store.get(conversation.conversation_id).state is ConversationState.ARCHIVED
    assert [type(event) for event in received] == [ConversationArchived]
    store.close()


def test_archive_unknown_conversation_raises(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()

    with pytest.raises(ConversationNotFoundError):
        store.archive(generate_id(), app_context)
    store.close()


def test_archive_twice_raises(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()
    conversation = store.create(app_context)
    store.archive(conversation.conversation_id, app_context)

    with pytest.raises(ConversationValidationError):
        store.archive(conversation.conversation_id, app_context)
    store.close()


def test_archived_conversation_stays_readable(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()
    conversation = store.create(app_context)
    message = Message(role=MessageRole.USER, content="hello")
    store.append(conversation.conversation_id, message, app_context)
    store.archive(conversation.conversation_id, app_context)

    assert store.get(conversation.conversation_id).messages == (message,)
    store.close()


# --- durability: the reason this store exists --------------------------------


def test_conversation_survives_reopening_the_store(tmp_path: Path) -> None:
    path = tmp_path / "conversations.db"
    app_context = make_application_context()
    store = SQLiteConversationStore(path)
    conversation = store.create(app_context, title="Chat", metadata={"channel": "console"})
    store.append(conversation.conversation_id, Message(role=MessageRole.USER, content="hi"), app_context)
    store.close()

    reopened = SQLiteConversationStore(path)
    restored = reopened.get(conversation.conversation_id)

    assert restored.title == "Chat"
    assert restored.metadata == {"channel": "console"}
    assert [message.content for message in restored.messages] == ["hi"]
    reopened.close()


def test_messages_survive_reopening_in_append_order(tmp_path: Path) -> None:
    path = tmp_path / "conversations.db"
    app_context = make_application_context()
    store = SQLiteConversationStore(path)
    conversation = store.create(app_context)
    for text in ("first", "second", "third"):
        store.append(conversation.conversation_id, Message(role=MessageRole.USER, content=text), app_context)
    store.close()

    reopened = SQLiteConversationStore(path)
    restored = reopened.get(conversation.conversation_id)

    assert [message.content for message in restored.messages] == ["first", "second", "third"]
    reopened.close()


def test_archived_state_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "conversations.db"
    app_context = make_application_context()
    store = SQLiteConversationStore(path)
    conversation = store.create(app_context)
    store.archive(conversation.conversation_id, app_context)
    store.close()

    reopened = SQLiteConversationStore(path)

    assert reopened.get(conversation.conversation_id).state is ConversationState.ARCHIVED
    reopened.close()


def test_two_conversations_do_not_mix_messages(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app_context = make_application_context()
    first = store.create(app_context)
    second = store.create(app_context)
    store.append(first.conversation_id, Message(role=MessageRole.USER, content="to first"), app_context)
    store.append(second.conversation_id, Message(role=MessageRole.USER, content="to second"), app_context)

    assert [m.content for m in store.get(first.conversation_id).messages] == ["to first"]
    assert [m.content for m in store.get(second.conversation_id).messages] == ["to second"]
    store.close()
