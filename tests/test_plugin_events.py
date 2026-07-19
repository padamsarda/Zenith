"""Tests for the concrete plugin lifecycle events."""

from __future__ import annotations

import pytest

from shared.events.event import Event
from runtime.plugins.events import (
    PluginDisabled,
    PluginEnabled,
    PluginFailed,
    PluginRegistered,
    PluginUnregistered,
)

ALL_PLUGIN_EVENT_TYPES = (
    PluginRegistered,
    PluginEnabled,
    PluginDisabled,
    PluginUnregistered,
    PluginFailed,
)


@pytest.mark.parametrize("event_type", ALL_PLUGIN_EVENT_TYPES)
def test_plugin_event_is_an_event(event_type: type[Event]) -> None:
    event = event_type(source="plugin_registry")

    assert isinstance(event, Event)


@pytest.mark.parametrize("event_type", ALL_PLUGIN_EVENT_TYPES)
def test_plugin_event_name_matches_class(event_type: type[Event]) -> None:
    event = event_type(source="plugin_registry")

    assert event.name == event_type.__name__


def test_plugin_registered_carries_payload() -> None:
    event = PluginRegistered(source="plugin_registry", payload={"plugin_id": "p", "name": "P"})

    assert event.payload == {"plugin_id": "p", "name": "P"}


def test_plugin_failed_carries_reason() -> None:
    event = PluginFailed(source="plugin_registry", payload={"reason": "boom"})

    assert event.payload["reason"] == "boom"


def test_plugin_enabled_carries_plugin_id() -> None:
    event = PluginEnabled(source="plugin_registry", payload={"plugin_id": "p"})

    assert event.payload["plugin_id"] == "p"


def test_plugin_disabled_carries_plugin_id() -> None:
    event = PluginDisabled(source="plugin_registry", payload={"plugin_id": "p"})

    assert event.payload["plugin_id"] == "p"


def test_plugin_unregistered_carries_plugin_id() -> None:
    event = PluginUnregistered(source="plugin_registry", payload={"plugin_id": "p"})

    assert event.payload["plugin_id"] == "p"


def test_plugin_events_are_distinct_types() -> None:
    assert len(set(ALL_PLUGIN_EVENT_TYPES)) == 5
