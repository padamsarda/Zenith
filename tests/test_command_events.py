"""Tests for the concrete command lifecycle events."""

from __future__ import annotations

import pytest

from runtime.commands.events import (
    CommandCancelled,
    CommandCompleted,
    CommandCreated,
    CommandFailed,
    CommandStarted,
)
from shared.events.event import Event

ALL_COMMAND_EVENT_TYPES = (
    CommandCreated,
    CommandStarted,
    CommandCompleted,
    CommandFailed,
    CommandCancelled,
)


@pytest.mark.parametrize("event_type", ALL_COMMAND_EVENT_TYPES)
def test_command_event_is_an_event(event_type: type[Event]) -> None:
    event = event_type(source="command_executor")

    assert isinstance(event, Event)


@pytest.mark.parametrize("event_type", ALL_COMMAND_EVENT_TYPES)
def test_command_event_name_matches_class(event_type: type[Event]) -> None:
    event = event_type(source="command_executor")

    assert event.name == event_type.__name__


def test_command_created_carries_payload() -> None:
    event = CommandCreated(
        source="command_executor", payload={"command_id": "abc", "name": "ping"}
    )

    assert event.payload == {"command_id": "abc", "name": "ping"}


def test_command_failed_carries_reason() -> None:
    event = CommandFailed(source="command_executor", payload={"reason": "boom"})

    assert event.payload["reason"] == "boom"


def test_command_cancelled_carries_reason() -> None:
    event = CommandCancelled(source="command_executor", payload={"reason": "cancelled"})

    assert event.payload["reason"] == "cancelled"


def test_command_completed_carries_duration() -> None:
    event = CommandCompleted(source="command_executor", payload={"duration_seconds": 0.5})

    assert event.payload["duration_seconds"] == 0.5


def test_command_events_are_distinct_types() -> None:
    assert len(set(ALL_COMMAND_EVENT_TYPES)) == 5
