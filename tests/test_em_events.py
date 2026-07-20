"""Tests for the Engineering Manager event types."""

from __future__ import annotations

import dataclasses

import pytest

from engineering_manager.events import (
    AccountAdded,
    AccountRemoved,
    AttentionRequired,
    PlanAdded,
    PlanStatusChanged,
    ProjectAdded,
    ProjectStatusChanged,
    SessionStarted,
    SessionStatusChanged,
    TaskAdded,
    TaskDependencyAdded,
    TaskStatusChanged,
)
from shared.events.event import Event

ALL_EVENT_TYPES = (
    ProjectAdded,
    ProjectStatusChanged,
    PlanAdded,
    PlanStatusChanged,
    TaskAdded,
    TaskDependencyAdded,
    TaskStatusChanged,
    SessionStarted,
    SessionStatusChanged,
    AttentionRequired,
    AccountAdded,
    AccountRemoved,
)


@pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
def test_event_type_is_a_frozen_event_subclass(event_type: type[Event]) -> None:
    assert issubclass(event_type, Event)

    event = event_type(source="engineering_manager")
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.source = "other"  # type: ignore[misc]


@pytest.mark.parametrize("event_type", ALL_EVENT_TYPES)
def test_event_name_matches_class_name(event_type: type[Event]) -> None:
    event = event_type(source="engineering_manager")

    assert event.name == event_type.__name__


def test_event_payload_carries_extra_data() -> None:
    event = TaskStatusChanged(
        source="engineering_manager",
        payload={"task_id": "x", "from": "DRAFT", "to": "READY"},
    )

    assert event.payload["to"] == "READY"
