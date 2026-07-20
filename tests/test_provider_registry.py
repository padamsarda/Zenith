"""Tests for the AssistantProviderRegistry."""

from __future__ import annotations

import pytest

from runtime.exceptions import (
    AssistantProviderNotFoundError,
    AssistantProviderRegistrationError,
)
from runtime.providers.base import AssistantProvider, AssistantTurn, TurnBrief
from runtime.providers.registry import AssistantProviderRegistry
from shared.exceptions import ValidationError


class NamedProvider(AssistantProvider):
    """A concrete provider with an injectable ID."""

    def __init__(self, provider_id: str = "test") -> None:
        self._provider_id = provider_id

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def name(self) -> str:
        return "Test"

    def generate_turn(self, brief: TurnBrief) -> AssistantTurn:
        return AssistantTurn(text="hello")


def test_register_stores_the_provider() -> None:
    registry = AssistantProviderRegistry()
    provider = NamedProvider()

    registry.register(provider)

    assert registry.get("test") is provider
    assert registry.has("test")


def test_register_blank_id_raises() -> None:
    with pytest.raises(ValidationError):
        AssistantProviderRegistry().register(NamedProvider(provider_id="  "))


def test_register_duplicate_id_raises() -> None:
    registry = AssistantProviderRegistry()
    registry.register(NamedProvider())

    with pytest.raises(AssistantProviderRegistrationError):
        registry.register(NamedProvider())


def test_get_unknown_id_raises() -> None:
    with pytest.raises(AssistantProviderNotFoundError):
        AssistantProviderRegistry().get("missing")


def test_has_reports_absence() -> None:
    assert not AssistantProviderRegistry().has("missing")


def test_list_returns_snapshot_in_registration_order() -> None:
    registry = AssistantProviderRegistry()
    first = NamedProvider(provider_id="first")
    second = NamedProvider(provider_id="second")
    registry.register(first)
    registry.register(second)

    listed = registry.list()
    listed.clear()

    assert registry.list() == [first, second]
