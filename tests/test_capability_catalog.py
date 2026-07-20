"""Tests for the CapabilityCatalog and build_catalog."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

import pytest

from configs.config import Config
from runtime.assistant.request import AssistantRequest
from runtime.capabilities.catalog import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
    build_catalog,
)
from runtime.capabilities.skill import Skill
from runtime.capabilities.skill_registry import SkillRegistry
from runtime.capabilities.tool import Tool, ToolParameter
from runtime.capabilities.tool_registry import ToolRegistry
from runtime.commands.context import CommandContext
from runtime.context import ApplicationContext


class NamedTool(Tool):
    """A concrete tool with an injectable ID."""

    def __init__(self, tool_id: str) -> None:
        self._tool_id = tool_id

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return f"Tool {self._tool_id}"

    @property
    def description(self) -> str:
        return f"Does {self._tool_id}."

    @property
    def parameters(self) -> tuple[ToolParameter, ...]:
        return (ToolParameter(name="input"),)

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> Any:
        return None


class NamedSkill(Skill):
    """A concrete skill with an injectable ID."""

    def __init__(self, skill_id: str) -> None:
        self._skill_id = skill_id

    @property
    def skill_id(self) -> str:
        return self._skill_id

    @property
    def name(self) -> str:
        return f"Skill {self._skill_id}"

    @property
    def description(self) -> str:
        return f"Teaches {self._skill_id}."

    def instructions(self, request: AssistantRequest) -> str:
        return "..."


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.catalog"))


def test_empty_registries_build_an_empty_catalog() -> None:
    catalog = build_catalog(ToolRegistry(), SkillRegistry())

    assert catalog.tools == ()
    assert catalog.skills == ()
    assert catalog.descriptors() == ()


def test_tool_descriptor_carries_the_tool_declaration() -> None:
    tools = ToolRegistry()
    tools.register(NamedTool("clock"), make_application_context())

    descriptor = build_catalog(tools, SkillRegistry()).tools[0]

    assert descriptor.kind is CapabilityKind.TOOL
    assert descriptor.capability_id == "clock"
    assert descriptor.name == "Tool clock"
    assert descriptor.description == "Does clock."
    assert descriptor.parameters == (ToolParameter(name="input"),)


def test_skill_descriptor_carries_the_skill_declaration() -> None:
    skills = SkillRegistry()
    skills.register(NamedSkill("greeting"), make_application_context())

    descriptor = build_catalog(ToolRegistry(), skills).skills[0]

    assert descriptor.kind is CapabilityKind.SKILL
    assert descriptor.capability_id == "greeting"
    assert descriptor.parameters == ()


def test_descriptors_are_sorted_by_id_regardless_of_registration_order() -> None:
    app_context = make_application_context()
    tools = ToolRegistry()
    tools.register(NamedTool("zulu"), app_context)
    tools.register(NamedTool("alpha"), app_context)
    skills = SkillRegistry()
    skills.register(NamedSkill("night"), app_context)
    skills.register(NamedSkill("dawn"), app_context)

    catalog = build_catalog(tools, skills)

    assert [descriptor.capability_id for descriptor in catalog.tools] == ["alpha", "zulu"]
    assert [descriptor.capability_id for descriptor in catalog.skills] == ["dawn", "night"]


def test_descriptors_lists_tools_before_skills() -> None:
    app_context = make_application_context()
    tools = ToolRegistry()
    tools.register(NamedTool("clock"), app_context)
    skills = SkillRegistry()
    skills.register(NamedSkill("greeting"), app_context)

    kinds = [descriptor.kind for descriptor in build_catalog(tools, skills).descriptors()]

    assert kinds == [CapabilityKind.TOOL, CapabilityKind.SKILL]


def test_catalog_is_frozen() -> None:
    catalog = CapabilityCatalog(tools=(), skills=())

    with pytest.raises(dataclasses.FrozenInstanceError):
        catalog.tools = ()  # type: ignore[misc]


def test_descriptor_is_frozen() -> None:
    descriptor = CapabilityDescriptor(
        kind=CapabilityKind.TOOL, capability_id="clock", name="Clock", description="Time."
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        descriptor.name = "changed"  # type: ignore[misc]
