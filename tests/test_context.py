"""Tests for the ApplicationContext."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from configs.config import Config
from runtime.commands.executor import CommandExecutor
from runtime.context import ApplicationContext
from runtime.events.bus import EventBus
from runtime.events.event import Event
from runtime.plugins.registry import PluginRegistry
from runtime.registry import ServiceRegistry
from runtime.state import RuntimeState


class SampleContextEvent(Event):
    """A minimal event used to test event bus isolation between contexts."""


def make_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.context"))


def test_context_starts_in_initializing_state() -> None:
    context = make_context()

    assert context.state is RuntimeState.INITIALIZING


def test_context_has_default_version() -> None:
    context = make_context()

    assert isinstance(context.version, str)
    assert context.version


def test_context_started_at_is_timezone_aware() -> None:
    context = make_context()

    assert isinstance(context.started_at, datetime)
    assert context.started_at.tzinfo == timezone.utc


def test_context_owns_a_service_registry() -> None:
    context = make_context()

    assert isinstance(context.services, ServiceRegistry)


def test_context_owns_an_event_bus() -> None:
    context = make_context()

    assert isinstance(context.events, EventBus)


def test_context_owns_a_command_executor() -> None:
    context = make_context()

    assert isinstance(context.commands, CommandExecutor)


def test_two_contexts_have_independent_command_executors() -> None:
    first = make_context()
    second = make_context()

    assert first.commands is not second.commands


def test_context_owns_a_plugin_registry() -> None:
    context = make_context()

    assert isinstance(context.plugins, PluginRegistry)


def test_two_contexts_have_independent_plugin_registries() -> None:
    first = make_context()
    second = make_context()

    assert first.plugins is not second.plugins


def test_two_contexts_have_independent_registries() -> None:
    first = make_context()
    second = make_context()

    first.services.register("thing", object())

    assert second.services.has("thing") is False


def test_two_contexts_have_independent_event_buses() -> None:
    first = make_context()
    second = make_context()
    received: list[Event] = []

    first.events.subscribe(SampleContextEvent, received.append)
    second.events.emit(SampleContextEvent(source="test"))

    assert received == []


def test_context_state_can_be_updated() -> None:
    context = make_context()

    context.state = RuntimeState.RUNNING

    assert context.state is RuntimeState.RUNNING


def test_context_config_can_be_replaced() -> None:
    context = make_context()
    new_config = Config(debug=True)

    context.config = new_config

    assert context.config is new_config
