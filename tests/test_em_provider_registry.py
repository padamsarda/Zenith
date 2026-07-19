"""Tests for the ProviderRegistry."""

from __future__ import annotations

import pytest

from engineering_manager.exceptions import (
    DomainValidationError,
    ProviderAlreadyRegisteredError,
    ProviderNotFoundError,
)
from engineering_manager.providers.in_memory import InMemoryProvider
from engineering_manager.providers.registry import ProviderRegistry


def test_register_and_get_provider() -> None:
    registry = ProviderRegistry()
    provider = InMemoryProvider()

    registry.register(provider)

    assert registry.get("in-memory") is provider


def test_has_reports_registration() -> None:
    registry = ProviderRegistry()

    assert not registry.has("in-memory")
    registry.register(InMemoryProvider())
    assert registry.has("in-memory")


def test_register_duplicate_id_raises() -> None:
    registry = ProviderRegistry()
    registry.register(InMemoryProvider())

    with pytest.raises(ProviderAlreadyRegisteredError):
        registry.register(InMemoryProvider())


def test_register_blank_provider_id_raises() -> None:
    registry = ProviderRegistry()

    with pytest.raises(DomainValidationError):
        registry.register(InMemoryProvider(provider_id="  "))


def test_get_unknown_provider_raises() -> None:
    registry = ProviderRegistry()

    with pytest.raises(ProviderNotFoundError):
        registry.get("missing")


def test_unregister_removes_provider() -> None:
    registry = ProviderRegistry()
    registry.register(InMemoryProvider())

    registry.unregister("in-memory")

    assert not registry.has("in-memory")


def test_unregister_unknown_provider_raises() -> None:
    registry = ProviderRegistry()

    with pytest.raises(ProviderNotFoundError):
        registry.unregister("missing")


def test_list_returns_snapshot_of_providers() -> None:
    registry = ProviderRegistry()
    first = InMemoryProvider(provider_id="first")
    second = InMemoryProvider(provider_id="second")
    registry.register(first)
    registry.register(second)

    providers = registry.list()

    assert providers == [first, second]
    providers.clear()
    assert registry.list() == [first, second]
