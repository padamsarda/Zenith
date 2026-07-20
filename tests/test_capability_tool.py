"""Tests for the Tool base class and ToolParameter."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from runtime.capabilities.tool import Tool, ToolParameter
from runtime.commands.context import CommandContext


class ClockTool(Tool):
    """A minimal concrete tool."""

    @property
    def tool_id(self) -> str:
        return "clock"

    @property
    def name(self) -> str:
        return "Clock"

    @property
    def description(self) -> str:
        return "Tells the current time."

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> Any:
        return "12:00"


class GreeterTool(ClockTool):
    """A tool that declares parameters."""

    @property
    def tool_id(self) -> str:
        return "greeter"

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return (ToolParameter(name="who", description="Who to greet"),)


def test_tool_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        Tool()  # type: ignore[abstract]


def test_concrete_tool_exposes_identity() -> None:
    tool = ClockTool()

    assert tool.tool_id == "clock"
    assert tool.name == "Clock"
    assert tool.description == "Tells the current time."


def test_parameters_default_to_empty() -> None:
    assert ClockTool().parameters == ()


def test_declared_parameters_are_returned() -> None:
    parameters = GreeterTool().parameters

    assert len(parameters) == 1
    assert parameters[0].name == "who"


def test_tool_parameter_defaults() -> None:
    parameter = ToolParameter(name="who")

    assert parameter.description is None
    assert parameter.required is True


def test_tool_parameter_is_frozen() -> None:
    parameter = ToolParameter(name="who")

    with pytest.raises(dataclasses.FrozenInstanceError):
        parameter.name = "changed"  # type: ignore[misc]
