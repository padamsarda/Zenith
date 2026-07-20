"""Tests for the capability validation guard functions."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.assistant.request import AssistantRequest
from runtime.capabilities.skill import Skill
from runtime.capabilities.tool import Tool, ToolParameter
from runtime.capabilities.validation import (
    validate_capability_id,
    validate_capability_text,
    validate_skill,
    validate_tool,
)
from runtime.commands.context import CommandContext
from runtime.exceptions import CapabilityValidationError


class ConfigurableTool(Tool):
    """A tool whose identity fields are injectable for validation tests."""

    def __init__(
        self,
        tool_id: str = "clock",
        name: str = "Clock",
        description: str = "Tells the time.",
        parameters: tuple[ToolParameter, ...] = (),
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._description = description
        self._parameters = parameters

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return self._parameters

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> Any:
        return None


class ConfigurableSkill(Skill):
    """A skill whose identity fields are injectable for validation tests."""

    def __init__(
        self,
        skill_id: str = "greeting",
        name: str = "Greeting",
        description: str = "How to greet.",
    ) -> None:
        self._skill_id = skill_id
        self._name = name
        self._description = description

    @property
    def skill_id(self) -> str:
        return self._skill_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def instructions(self, request: AssistantRequest) -> str:
        return "Greet warmly."


# --- validate_capability_id ---------------------------------------------


def test_valid_id_passes() -> None:
    validate_capability_id("clock")


@pytest.mark.parametrize("bad_id", ["", "  ", " clock", "clock ", 42])
def test_invalid_id_raises(bad_id: Any) -> None:
    with pytest.raises(CapabilityValidationError):
        validate_capability_id(bad_id)


# --- validate_capability_text -------------------------------------------


def test_valid_text_passes() -> None:
    validate_capability_text("Tells the time.", "description")


@pytest.mark.parametrize("bad_text", ["", "   ", None, 42])
def test_invalid_text_raises(bad_text: Any) -> None:
    with pytest.raises(CapabilityValidationError):
        validate_capability_text(bad_text, "description")


# --- validate_tool ------------------------------------------------------


def test_valid_tool_passes() -> None:
    validate_tool(ConfigurableTool(parameters=(ToolParameter(name="who"),)))


def test_tool_with_blank_id_raises() -> None:
    with pytest.raises(CapabilityValidationError):
        validate_tool(ConfigurableTool(tool_id="  "))


def test_tool_with_blank_name_raises() -> None:
    with pytest.raises(CapabilityValidationError):
        validate_tool(ConfigurableTool(name=""))


def test_tool_with_blank_description_raises() -> None:
    with pytest.raises(CapabilityValidationError):
        validate_tool(ConfigurableTool(description="  "))


def test_tool_with_non_parameter_raises() -> None:
    tool = ConfigurableTool(parameters=("who",))  # type: ignore[arg-type]

    with pytest.raises(CapabilityValidationError):
        validate_tool(tool)


def test_tool_with_blank_parameter_name_raises() -> None:
    tool = ConfigurableTool(parameters=(ToolParameter(name=" "),))

    with pytest.raises(CapabilityValidationError):
        validate_tool(tool)


# --- validate_skill -----------------------------------------------------


def test_valid_skill_passes() -> None:
    validate_skill(ConfigurableSkill())


def test_skill_with_blank_id_raises() -> None:
    with pytest.raises(CapabilityValidationError):
        validate_skill(ConfigurableSkill(skill_id=""))


def test_skill_with_blank_name_raises() -> None:
    with pytest.raises(CapabilityValidationError):
        validate_skill(ConfigurableSkill(name="  "))


def test_skill_with_blank_description_raises() -> None:
    with pytest.raises(CapabilityValidationError):
        validate_skill(ConfigurableSkill(description=""))
