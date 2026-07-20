"""Tests for the ToolRegistry."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from configs.config import Config
from runtime.capabilities.events import ToolRegistered, ToolUnregistered
from runtime.capabilities.tool import Tool
from runtime.capabilities.tool_registry import ToolRegistry
from runtime.commands.context import CommandContext
from runtime.context import ApplicationContext
from runtime.exceptions import (
    CapabilityValidationError,
    ToolNotFoundError,
    ToolRegistrationError,
)
from shared.events.event import Event


class NamedTool(Tool):
    """A concrete tool with an injectable ID."""

    def __init__(self, tool_id: str = "clock") -> None:
        self._tool_id = tool_id

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return "Clock"

    @property
    def description(self) -> str:
        return "Tells the time."

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> Any:
        return "12:00"


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.tool_registry"))


def subscribe_all(app_context: ApplicationContext) -> list[Event]:
    received: list[Event] = []
    for event_type in (ToolRegistered, ToolUnregistered):
        app_context.events.subscribe(event_type, received.append)
    return received


def test_register_stores_the_tool() -> None:
    registry = ToolRegistry()
    app_context = make_application_context()
    tool = NamedTool()

    registry.register(tool, app_context)

    assert registry.get("clock") is tool
    assert registry.has("clock")


def test_register_emits_tool_registered() -> None:
    registry = ToolRegistry()
    app_context = make_application_context()
    received = subscribe_all(app_context)

    registry.register(NamedTool(), app_context)

    assert [type(event) for event in received] == [ToolRegistered]
    assert received[0].payload == {"tool_id": "clock", "name": "Clock"}


def test_register_duplicate_id_raises() -> None:
    registry = ToolRegistry()
    app_context = make_application_context()
    registry.register(NamedTool(), app_context)

    with pytest.raises(ToolRegistrationError):
        registry.register(NamedTool(), app_context)


def test_register_invalid_tool_raises_and_stores_nothing() -> None:
    registry = ToolRegistry()
    app_context = make_application_context()
    received = subscribe_all(app_context)

    with pytest.raises(CapabilityValidationError):
        registry.register(NamedTool(tool_id="  "), app_context)
    assert registry.list() == []
    assert received == []


def test_unregister_removes_and_emits() -> None:
    registry = ToolRegistry()
    app_context = make_application_context()
    registry.register(NamedTool(), app_context)
    received = subscribe_all(app_context)

    registry.unregister("clock", app_context)

    assert not registry.has("clock")
    assert [type(event) for event in received] == [ToolUnregistered]


def test_unregister_unknown_id_raises() -> None:
    registry = ToolRegistry()
    app_context = make_application_context()

    with pytest.raises(ToolNotFoundError):
        registry.unregister("missing", app_context)


def test_get_unknown_id_raises() -> None:
    with pytest.raises(ToolNotFoundError):
        ToolRegistry().get("missing")


def test_list_returns_snapshot_in_registration_order() -> None:
    registry = ToolRegistry()
    app_context = make_application_context()
    zulu = NamedTool(tool_id="zulu")
    alpha = NamedTool(tool_id="alpha")
    registry.register(zulu, app_context)
    registry.register(alpha, app_context)

    listed = registry.list()
    listed.clear()

    assert registry.list() == [zulu, alpha]
