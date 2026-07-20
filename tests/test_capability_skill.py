"""Tests for the Skill base class."""

from __future__ import annotations

import pytest

from runtime.assistant.request import AssistantRequest
from runtime.capabilities.skill import Skill
from shared.utils.uuid_utils import generate_id


class GreetingSkill(Skill):
    """A minimal concrete skill."""

    @property
    def skill_id(self) -> str:
        return "greeting"

    @property
    def name(self) -> str:
        return "Greeting"

    @property
    def description(self) -> str:
        return "How to greet people."

    def instructions(self, request: AssistantRequest) -> str:
        return "Always greet warmly."


class EagerSkill(GreetingSkill):
    """A skill that opts into automatic activation."""

    @property
    def skill_id(self) -> str:
        return "eager"

    def applies_to(self, request: AssistantRequest) -> bool:
        return True


def make_request() -> AssistantRequest:
    return AssistantRequest(conversation_id=generate_id(), text="hello")


def test_skill_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        Skill()  # type: ignore[abstract]


def test_concrete_skill_exposes_identity() -> None:
    skill = GreetingSkill()

    assert skill.skill_id == "greeting"
    assert skill.name == "Greeting"
    assert skill.description == "How to greet people."


def test_instructions_receive_the_request() -> None:
    assert GreetingSkill().instructions(make_request()) == "Always greet warmly."


def test_applies_to_defaults_to_false() -> None:
    assert GreetingSkill().applies_to(make_request()) is False


def test_applies_to_can_be_overridden() -> None:
    assert EagerSkill().applies_to(make_request()) is True
