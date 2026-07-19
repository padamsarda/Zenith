"""Tests for the Event base class and concrete lifecycle events."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from shared.events.event import Event
from runtime.events.lifecycle_events import (
    ApplicationStarted,
    ApplicationStarting,
    ApplicationStartupFailed,
    ApplicationStopped,
    ApplicationStopping,
    ConfigurationLoaded,
    ConfigurationLoadFailed,
)

ALL_EVENT_TYPES = (
    ApplicationStarting,
    ApplicationStarted,
    ApplicationStopping,
    ApplicationStopped,
    ApplicationStartupFailed,
    ConfigurationLoaded,
    ConfigurationLoadFailed,
)


def test_event_has_uuid_id() -> None:
    event = Event(source="test")

    assert isinstance(event.event_id, UUID)


def test_event_has_timezone_aware_timestamp() -> None:
    event = Event(source="test")

    assert isinstance(event.timestamp, datetime)
    assert event.timestamp.tzinfo == timezone.utc


def test_event_default_payload_is_empty_dict() -> None:
    event = Event(source="test")

    assert event.payload == {}


def test_event_payload_can_carry_data() -> None:
    event = Event(source="test", payload={"reason": "because"})

    assert event.payload == {"reason": "because"}


def test_event_name_defaults_to_class_name() -> None:
    event = Event(source="test")

    assert event.name == "Event"


def test_event_is_immutable() -> None:
    event = Event(source="test")

    with pytest.raises(AttributeError):
        event.source = "other"  # type: ignore[misc]


def test_two_events_have_different_ids() -> None:
    first = Event(source="test")
    second = Event(source="test")

    assert first.event_id != second.event_id


@pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
def test_lifecycle_event_name_matches_class(event_type: type[Event]) -> None:
    event = event_type(source="runtime")

    assert event.name == event_type.__name__


@pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
def test_lifecycle_event_is_an_event(event_type: type[Event]) -> None:
    event = event_type(source="runtime")

    assert isinstance(event, Event)


def test_lifecycle_event_carries_source() -> None:
    event = ApplicationStarting(source="runtime")

    assert event.source == "runtime"
