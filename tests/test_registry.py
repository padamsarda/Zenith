"""Tests for the ServiceRegistry."""

from __future__ import annotations

import pytest

from runtime.exceptions import ServiceAlreadyRegisteredError, ServiceNotFoundError, ValidationError
from runtime.registry import ServiceRegistry


def test_register_and_get_returns_same_instance() -> None:
    registry = ServiceRegistry()
    service = object()

    registry.register("thing", service)

    assert registry.get("thing") is service


def test_has_returns_false_before_registration() -> None:
    registry = ServiceRegistry()

    assert registry.has("thing") is False


def test_has_returns_true_after_registration() -> None:
    registry = ServiceRegistry()
    registry.register("thing", object())

    assert registry.has("thing") is True


def test_register_duplicate_name_raises() -> None:
    registry = ServiceRegistry()
    registry.register("thing", object())

    with pytest.raises(ServiceAlreadyRegisteredError):
        registry.register("thing", object())


def test_register_invalid_name_raises_validation_error() -> None:
    registry = ServiceRegistry()

    with pytest.raises(ValidationError):
        registry.register("", object())


def test_get_missing_service_raises() -> None:
    registry = ServiceRegistry()

    with pytest.raises(ServiceNotFoundError):
        registry.get("missing")


def test_unregister_removes_service() -> None:
    registry = ServiceRegistry()
    registry.register("thing", object())

    registry.unregister("thing")

    assert registry.has("thing") is False


def test_unregister_missing_service_raises() -> None:
    registry = ServiceRegistry()

    with pytest.raises(ServiceNotFoundError):
        registry.unregister("missing")


def test_get_after_unregister_raises() -> None:
    registry = ServiceRegistry()
    registry.register("thing", object())
    registry.unregister("thing")

    with pytest.raises(ServiceNotFoundError):
        registry.get("thing")


def test_reregister_after_unregister_succeeds() -> None:
    registry = ServiceRegistry()
    registry.register("thing", "first")
    registry.unregister("thing")

    registry.register("thing", "second")

    assert registry.get("thing") == "second"


def test_registry_holds_multiple_independent_services() -> None:
    registry = ServiceRegistry()
    registry.register("a", 1)
    registry.register("b", 2)

    assert registry.get("a") == 1
    assert registry.get("b") == 2
