"""Tests for the concrete conversation events."""

from __future__ import annotations

import pytest

from runtime.conversation.events import (
    ConversationArchived,
    ConversationStarted,
    MessageAppended,
)
from shared.events.event import Event

ALL_CONVERSATION_EVENT_TYPES = (
    ConversationStarted,
    ConversationArchived,
    MessageAppended,
)


@pytest.mark.parametrize("event_type", ALL_CONVERSATION_EVENT_TYPES)
def test_conversation_event_is_an_event(event_type: type[Event]) -> None:
    event = event_type(source="conversation_store")

    assert isinstance(event, Event)


@pytest.mark.parametrize("event_type", ALL_CONVERSATION_EVENT_TYPES)
def test_conversation_event_name_matches_class(event_type: type[Event]) -> None:
    event = event_type(source="conversation_store")

    assert event.name == event_type.__name__


def test_conversation_started_carries_payload() -> None:
    event = ConversationStarted(
        source="conversation_store", payload={"conversation_id": "abc", "title": "Chat"}
    )

    assert event.payload == {"conversation_id": "abc", "title": "Chat"}


def test_message_appended_carries_role() -> None:
    event = MessageAppended(source="conversation_store", payload={"role": "USER"})

    assert event.payload["role"] == "USER"


def test_conversation_events_are_distinct_types() -> None:
    assert len(set(ALL_CONVERSATION_EVENT_TYPES)) == 3
