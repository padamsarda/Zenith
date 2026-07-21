"""Tests for the engineering-workflow plugin: the first genuine Skill."""

from __future__ import annotations

import logging

import pytest

from configs.config import Config
from runtime.assistant.assembler import AssistantContextAssembler
from runtime.assistant.request import AssistantRequest
from runtime.context import ApplicationContext
from runtime.exceptions import PluginRegistrationError
from runtime.plugins.state import PluginState
from shared.utils.uuid_utils import generate_id

from plugins.engineering_workflow.plugin import (
    PLUGIN_ID,
    SKILL_ID,
    EngineeringWorkflowPlugin,
    EngineeringWorkflowSkill,
    create_plugin,
)


def make_application_context() -> ApplicationContext:
    return ApplicationContext(
        config=Config(), logger=logging.getLogger("test.plugin_engineering_workflow")
    )


def make_request(**overrides: object) -> AssistantRequest:
    fields: dict[str, object] = {"conversation_id": generate_id(), "text": "fix the bug"}
    fields.update(overrides)
    return AssistantRequest(**fields)  # type: ignore[arg-type]


# --- create_plugin() factory --------------------------------------------------


def test_create_plugin_returns_an_engineering_workflow_plugin() -> None:
    plugin = create_plugin()

    assert isinstance(plugin, EngineeringWorkflowPlugin)


def test_create_plugin_returns_a_fresh_instance_each_call() -> None:
    assert create_plugin() is not create_plugin()


# --- manifest -------------------------------------------------------------


def test_plugin_id_matches_module_constant() -> None:
    plugin = EngineeringWorkflowPlugin()

    assert plugin.id == PLUGIN_ID


def test_plugin_starts_in_created_state() -> None:
    plugin = EngineeringWorkflowPlugin()

    assert plugin.state is PluginState.CREATED


# --- registering through PluginRegistry -------------------------------------


def test_register_adds_the_skill_to_the_skill_registry() -> None:
    app_context = make_application_context()
    plugin = EngineeringWorkflowPlugin()

    app_context.plugins.register(plugin, app_context)

    assert app_context.skills.has(SKILL_ID) is True


def test_register_stores_the_engineering_workflow_skill() -> None:
    app_context = make_application_context()
    plugin = EngineeringWorkflowPlugin()

    app_context.plugins.register(plugin, app_context)

    assert isinstance(app_context.skills.get(SKILL_ID), EngineeringWorkflowSkill)


def test_unregister_removes_the_skill_from_the_skill_registry() -> None:
    app_context = make_application_context()
    plugin = EngineeringWorkflowPlugin()
    app_context.plugins.register(plugin, app_context)

    app_context.plugins.unregister(plugin, app_context)

    assert app_context.skills.has(SKILL_ID) is False


def test_two_plugin_instances_do_not_collide_on_skill_id() -> None:
    app_context = make_application_context()
    first = EngineeringWorkflowPlugin()
    second_manifest_plugin = create_plugin()
    app_context.plugins.register(first, app_context)

    # A second instance's manifest has the same plugin_id, so registering
    # it should fail the same way any duplicate plugin registration does,
    # without corrupting the first registration.
    with pytest.raises(PluginRegistrationError):
        app_context.plugins.register(second_manifest_plugin, app_context)

    assert app_context.skills.has(SKILL_ID) is True


# --- the skill itself ---------------------------------------------------------


def test_skill_id_matches_module_constant() -> None:
    skill = EngineeringWorkflowSkill()

    assert skill.skill_id == SKILL_ID


def test_skill_has_non_empty_name_and_description() -> None:
    skill = EngineeringWorkflowSkill()

    assert skill.name
    assert skill.description


def test_skill_does_not_apply_unasked() -> None:
    skill = EngineeringWorkflowSkill()

    assert skill.applies_to(make_request()) is False


def test_instructions_are_deterministic_for_the_same_request() -> None:
    skill = EngineeringWorkflowSkill()
    request = make_request()

    assert skill.instructions(request) == skill.instructions(request)


def test_instructions_are_the_same_across_different_requests() -> None:
    skill = EngineeringWorkflowSkill()

    first = skill.instructions(make_request(text="do task one"))
    second = skill.instructions(make_request(text="do task two"))

    assert first == second


def test_instructions_mention_testing_and_diffing() -> None:
    skill = EngineeringWorkflowSkill()

    instructions = skill.instructions(make_request())

    assert "test" in instructions.lower()
    assert "diff" in instructions.lower()


# --- end-to-end: skill is activatable through the assembler ------------------


def test_skill_becomes_active_when_named_by_request() -> None:
    app_context = make_application_context()
    app_context.plugins.register(EngineeringWorkflowPlugin(), app_context)
    conversation = app_context.conversations.create(app_context)
    request = make_request(
        conversation_id=conversation.conversation_id, metadata={"skills": [SKILL_ID]}
    )

    brief = AssistantContextAssembler().assemble(request, conversation, app_context)

    assert brief.instructions is not None
    assert "Engineering Workflow" in brief.instructions
