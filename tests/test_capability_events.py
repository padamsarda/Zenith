"""Tests for the concrete capability registry events."""

from __future__ import annotations

import pytest

from runtime.capabilities.events import (
    SkillRegistered,
    SkillUnregistered,
    ToolRegistered,
    ToolUnregistered,
)
from shared.events.event import Event

ALL_CAPABILITY_EVENT_TYPES = (
    ToolRegistered,
    ToolUnregistered,
    SkillRegistered,
    SkillUnregistered,
)


@pytest.mark.parametrize("event_type", ALL_CAPABILITY_EVENT_TYPES)
def test_capability_event_is_an_event(event_type: type[Event]) -> None:
    event = event_type(source="tool_registry")

    assert isinstance(event, Event)


@pytest.mark.parametrize("event_type", ALL_CAPABILITY_EVENT_TYPES)
def test_capability_event_name_matches_class(event_type: type[Event]) -> None:
    event = event_type(source="tool_registry")

    assert event.name == event_type.__name__


def test_tool_registered_carries_payload() -> None:
    event = ToolRegistered(source="tool_registry", payload={"tool_id": "clock", "name": "Clock"})

    assert event.payload == {"tool_id": "clock", "name": "Clock"}


def test_capability_events_are_distinct_types() -> None:
    assert len(set(ALL_CAPABILITY_EVENT_TYPES)) == 4
