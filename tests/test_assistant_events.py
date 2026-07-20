"""Tests for the concrete assistant engine events."""

from __future__ import annotations

import pytest

from runtime.assistant.events import (
    RequestCompleted,
    RequestFailed,
    RequestReceived,
    ToolCallCompleted,
    ToolCallDenied,
    ToolCallFailed,
    ToolCallRequested,
)
from shared.events.event import Event

ALL_ASSISTANT_EVENT_TYPES = (
    RequestReceived,
    RequestCompleted,
    RequestFailed,
    ToolCallRequested,
    ToolCallDenied,
    ToolCallCompleted,
    ToolCallFailed,
)


@pytest.mark.parametrize("event_type", ALL_ASSISTANT_EVENT_TYPES)
def test_assistant_event_is_an_event(event_type: type[Event]) -> None:
    event = event_type(source="assistant_engine")

    assert isinstance(event, Event)


@pytest.mark.parametrize("event_type", ALL_ASSISTANT_EVENT_TYPES)
def test_assistant_event_name_matches_class(event_type: type[Event]) -> None:
    event = event_type(source="assistant_engine")

    assert event.name == event_type.__name__


def test_request_failed_carries_reason() -> None:
    event = RequestFailed(source="assistant_engine", payload={"reason": "boom"})

    assert event.payload["reason"] == "boom"


def test_tool_call_requested_carries_ids() -> None:
    event = ToolCallRequested(
        source="assistant_engine",
        payload={"request_id": "r", "call_id": "c", "tool_id": "clock"},
    )

    assert event.payload == {"request_id": "r", "call_id": "c", "tool_id": "clock"}


def test_assistant_events_are_distinct_types() -> None:
    assert len(set(ALL_ASSISTANT_EVENT_TYPES)) == 7
