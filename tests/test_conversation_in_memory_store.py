"""Tests for InMemoryConversationStore."""

from __future__ import annotations

import logging

import pytest

from configs.config import Config
from runtime.context import ApplicationContext
from runtime.conversation.events import (
    ConversationArchived,
    ConversationStarted,
    MessageAppended,
)
from runtime.conversation.in_memory_store import InMemoryConversationStore
from runtime.conversation.message import Message, MessageRole
from runtime.conversation.state import ConversationState
from runtime.exceptions import ConversationNotFoundError, ConversationValidationError
from shared.events.event import Event
from shared.utils.uuid_utils import generate_id


def make_application_context() -> ApplicationContext:
    return ApplicationContext(
        config=Config(), logger=logging.getLogger("test.conversation_store")
    )


def subscribe_all(app_context: ApplicationContext) -> list[Event]:
    received: list[Event] = []
    for event_type in (ConversationStarted, ConversationArchived, MessageAppended):
        app_context.events.subscribe(event_type, received.append)
    return received


def test_create_returns_an_active_stored_conversation() -> None:
    store = InMemoryConversationStore()
    app_context = make_application_context()

    conversation = store.create(app_context, title="Chat")

    assert conversation.state is ConversationState.ACTIVE
    assert store.get(conversation.conversation_id) is conversation


def test_create_emits_conversation_started() -> None:
    store = InMemoryConversationStore()
    app_context = make_application_context()
    received = subscribe_all(app_context)

    conversation = store.create(app_context, title="Chat")

    assert [type(event) for event in received] == [ConversationStarted]
    assert received[0].payload == {
        "conversation_id": str(conversation.conversation_id),
        "title": "Chat",
    }


def test_get_unknown_conversation_raises() -> None:
    store = InMemoryConversationStore()

    with pytest.raises(ConversationNotFoundError):
        store.get(generate_id())


def test_has_reports_presence() -> None:
    store = InMemoryConversationStore()
    app_context = make_application_context()
    conversation = store.create(app_context)

    assert store.has(conversation.conversation_id)
    assert not store.has(generate_id())


def test_list_returns_snapshot_in_creation_order() -> None:
    store = InMemoryConversationStore()
    app_context = make_application_context()
    first = store.create(app_context)
    second = store.create(app_context)

    listed = store.list()
    listed.clear()

    assert store.list() == [first, second]


def test_append_adds_message_and_emits() -> None:
    store = InMemoryConversationStore()
    app_context = make_application_context()
    conversation = store.create(app_context)
    received = subscribe_all(app_context)
    message = Message(role=MessageRole.USER, content="hello")

    store.append(conversation.conversation_id, message, app_context)

    assert conversation.messages == (message,)
    assert [type(event) for event in received] == [MessageAppended]
    assert received[0].payload["role"] == "USER"
    assert received[0].payload["message_id"] == str(message.message_id)


def test_append_to_unknown_conversation_raises() -> None:
    store = InMemoryConversationStore()
    app_context = make_application_context()

    with pytest.raises(ConversationNotFoundError):
        store.append(
            generate_id(), Message(role=MessageRole.USER, content="hello"), app_context
        )


def test_append_invalid_message_raises_and_emits_nothing() -> None:
    store = InMemoryConversationStore()
    app_context = make_application_context()
    conversation = store.create(app_context)
    received = subscribe_all(app_context)

    with pytest.raises(ConversationValidationError):
        store.append(
            conversation.conversation_id,
            Message(role=MessageRole.USER, content=""),
            app_context,
        )
    assert received == []


def test_archive_transitions_and_emits() -> None:
    store = InMemoryConversationStore()
    app_context = make_application_context()
    conversation = store.create(app_context)
    received = subscribe_all(app_context)

    store.archive(conversation.conversation_id, app_context)

    assert conversation.state is ConversationState.ARCHIVED
    assert [type(event) for event in received] == [ConversationArchived]


def test_archive_unknown_conversation_raises() -> None:
    store = InMemoryConversationStore()
    app_context = make_application_context()

    with pytest.raises(ConversationNotFoundError):
        store.archive(generate_id(), app_context)


def test_archive_twice_raises() -> None:
    store = InMemoryConversationStore()
    app_context = make_application_context()
    conversation = store.create(app_context)
    store.archive(conversation.conversation_id, app_context)

    with pytest.raises(ConversationValidationError):
        store.archive(conversation.conversation_id, app_context)


def test_archived_conversation_stays_readable() -> None:
    store = InMemoryConversationStore()
    app_context = make_application_context()
    conversation = store.create(app_context)
    message = Message(role=MessageRole.USER, content="hello")
    store.append(conversation.conversation_id, message, app_context)
    store.archive(conversation.conversation_id, app_context)

    assert store.get(conversation.conversation_id).messages == (message,)
