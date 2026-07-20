"""Tests for the AssistantContextAssembler."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from configs.config import Config
from runtime.assistant.assembler import AssistantContextAssembler
from runtime.assistant.request import AssistantRequest
from runtime.capabilities.catalog import CapabilityKind
from runtime.capabilities.skill import Skill
from runtime.capabilities.tool import Tool
from runtime.commands.context import CommandContext
from runtime.context import ApplicationContext
from runtime.conversation.conversation import Conversation
from runtime.conversation.message import Message, MessageRole
from runtime.exceptions import RequestValidationError, SkillNotFoundError


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
        return "Tells the time."

    def invoke(self, context: CommandContext, arguments: dict[str, Any]) -> Any:
        return "12:00"


class NamedSkill(Skill):
    """A concrete skill with injectable ID and automatic activation."""

    def __init__(self, skill_id: str, applies: bool = False) -> None:
        self._skill_id = skill_id
        self._applies = applies

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
        return f"Instructions from {self._skill_id}."

    def applies_to(self, request: AssistantRequest) -> bool:
        return self._applies


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.assembler"))


def make_conversation(app_context: ApplicationContext) -> Conversation:
    return app_context.conversations.create(app_context)


def make_request(
    conversation: Conversation, metadata: dict[str, Any] | None = None
) -> AssistantRequest:
    return AssistantRequest(
        conversation_id=conversation.conversation_id, text="hello", metadata=metadata or {}
    )


def test_brief_carries_the_conversation_snapshot() -> None:
    app_context = make_application_context()
    conversation = make_conversation(app_context)
    message = Message(role=MessageRole.USER, content="hello")
    conversation.append(message)

    brief = AssistantContextAssembler().assemble(
        make_request(conversation), conversation, app_context
    )

    assert brief.conversation_id == conversation.conversation_id
    assert brief.messages == (message,)


def test_no_skills_means_no_instructions() -> None:
    app_context = make_application_context()
    conversation = make_conversation(app_context)

    brief = AssistantContextAssembler().assemble(
        make_request(conversation), conversation, app_context
    )

    assert brief.instructions is None


def test_catalog_reflects_registered_tools() -> None:
    app_context = make_application_context()
    app_context.tools.register(ClockTool(), app_context)
    conversation = make_conversation(app_context)

    brief = AssistantContextAssembler().assemble(
        make_request(conversation), conversation, app_context
    )

    assert [d.capability_id for d in brief.catalog.tools] == ["clock"]
    assert brief.catalog.tools[0].kind is CapabilityKind.TOOL


def test_named_skill_contributes_instructions() -> None:
    app_context = make_application_context()
    app_context.skills.register(NamedSkill("greeting"), app_context)
    conversation = make_conversation(app_context)
    request = make_request(conversation, metadata={"skills": ["greeting"]})

    brief = AssistantContextAssembler().assemble(request, conversation, app_context)

    assert brief.instructions == "[Skill: Skill greeting]\nInstructions from greeting."


def test_applying_skill_activates_unasked() -> None:
    app_context = make_application_context()
    app_context.skills.register(NamedSkill("eager", applies=True), app_context)
    conversation = make_conversation(app_context)

    brief = AssistantContextAssembler().assemble(
        make_request(conversation), conversation, app_context
    )

    assert brief.instructions == "[Skill: Skill eager]\nInstructions from eager."


def test_non_applying_unnamed_skill_stays_inactive() -> None:
    app_context = make_application_context()
    app_context.skills.register(NamedSkill("quiet"), app_context)
    conversation = make_conversation(app_context)

    brief = AssistantContextAssembler().assemble(
        make_request(conversation), conversation, app_context
    )

    assert brief.instructions is None


def test_active_skills_are_ordered_by_id_and_deduplicated() -> None:
    app_context = make_application_context()
    app_context.skills.register(NamedSkill("zulu", applies=True), app_context)
    app_context.skills.register(NamedSkill("alpha"), app_context)
    conversation = make_conversation(app_context)
    request = make_request(conversation, metadata={"skills": ["zulu", "alpha"]})

    brief = AssistantContextAssembler().assemble(request, conversation, app_context)

    assert brief.instructions == (
        "[Skill: Skill alpha]\nInstructions from alpha."
        "\n\n"
        "[Skill: Skill zulu]\nInstructions from zulu."
    )


def test_unknown_named_skill_raises() -> None:
    app_context = make_application_context()
    conversation = make_conversation(app_context)
    request = make_request(conversation, metadata={"skills": ["missing"]})

    with pytest.raises(SkillNotFoundError):
        AssistantContextAssembler().assemble(request, conversation, app_context)


def test_non_list_skills_metadata_raises() -> None:
    app_context = make_application_context()
    conversation = make_conversation(app_context)
    request = make_request(conversation, metadata={"skills": "greeting"})

    with pytest.raises(RequestValidationError):
        AssistantContextAssembler().assemble(request, conversation, app_context)


def test_brief_metadata_is_a_copy_of_request_metadata() -> None:
    app_context = make_application_context()
    conversation = make_conversation(app_context)
    request = make_request(conversation, metadata={"provider": "echo"})

    brief = AssistantContextAssembler().assemble(request, conversation, app_context)
    request.metadata["provider"] = "changed"

    assert brief.metadata == {"provider": "echo"}
