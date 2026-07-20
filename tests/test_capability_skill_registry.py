"""Tests for the SkillRegistry."""

from __future__ import annotations

import logging

import pytest

from configs.config import Config
from runtime.assistant.request import AssistantRequest
from runtime.capabilities.events import SkillRegistered, SkillUnregistered
from runtime.capabilities.skill import Skill
from runtime.capabilities.skill_registry import SkillRegistry
from runtime.context import ApplicationContext
from runtime.exceptions import (
    CapabilityValidationError,
    SkillNotFoundError,
    SkillRegistrationError,
)
from shared.events.event import Event


class NamedSkill(Skill):
    """A concrete skill with an injectable ID."""

    def __init__(self, skill_id: str = "greeting") -> None:
        self._skill_id = skill_id

    @property
    def skill_id(self) -> str:
        return self._skill_id

    @property
    def name(self) -> str:
        return "Greeting"

    @property
    def description(self) -> str:
        return "How to greet."

    def instructions(self, request: AssistantRequest) -> str:
        return "Greet warmly."


def make_application_context() -> ApplicationContext:
    return ApplicationContext(config=Config(), logger=logging.getLogger("test.skill_registry"))


def subscribe_all(app_context: ApplicationContext) -> list[Event]:
    received: list[Event] = []
    for event_type in (SkillRegistered, SkillUnregistered):
        app_context.events.subscribe(event_type, received.append)
    return received


def test_register_stores_the_skill() -> None:
    registry = SkillRegistry()
    app_context = make_application_context()
    skill = NamedSkill()

    registry.register(skill, app_context)

    assert registry.get("greeting") is skill
    assert registry.has("greeting")


def test_register_emits_skill_registered() -> None:
    registry = SkillRegistry()
    app_context = make_application_context()
    received = subscribe_all(app_context)

    registry.register(NamedSkill(), app_context)

    assert [type(event) for event in received] == [SkillRegistered]
    assert received[0].payload == {"skill_id": "greeting", "name": "Greeting"}


def test_register_duplicate_id_raises() -> None:
    registry = SkillRegistry()
    app_context = make_application_context()
    registry.register(NamedSkill(), app_context)

    with pytest.raises(SkillRegistrationError):
        registry.register(NamedSkill(), app_context)


def test_register_invalid_skill_raises_and_stores_nothing() -> None:
    registry = SkillRegistry()
    app_context = make_application_context()
    received = subscribe_all(app_context)

    with pytest.raises(CapabilityValidationError):
        registry.register(NamedSkill(skill_id=""), app_context)
    assert registry.list() == []
    assert received == []


def test_unregister_removes_and_emits() -> None:
    registry = SkillRegistry()
    app_context = make_application_context()
    registry.register(NamedSkill(), app_context)
    received = subscribe_all(app_context)

    registry.unregister("greeting", app_context)

    assert not registry.has("greeting")
    assert [type(event) for event in received] == [SkillUnregistered]


def test_unregister_unknown_id_raises() -> None:
    registry = SkillRegistry()
    app_context = make_application_context()

    with pytest.raises(SkillNotFoundError):
        registry.unregister("missing", app_context)


def test_get_unknown_id_raises() -> None:
    with pytest.raises(SkillNotFoundError):
        SkillRegistry().get("missing")


def test_list_returns_snapshot_in_registration_order() -> None:
    registry = SkillRegistry()
    app_context = make_application_context()
    zulu = NamedSkill(skill_id="zulu")
    alpha = NamedSkill(skill_id="alpha")
    registry.register(zulu, app_context)
    registry.register(alpha, app_context)

    listed = registry.list()
    listed.clear()

    assert registry.list() == [zulu, alpha]
