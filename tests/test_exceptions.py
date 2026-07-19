"""Tests for the generic shared exception hierarchy."""

from __future__ import annotations

from shared.exceptions import (
    ConfigurationError,
    EventBusError,
    ValidationError,
    ZenithError,
    ZenithRuntimeError,
)


def test_zenith_error_is_an_exception() -> None:
    assert issubclass(ZenithError, Exception)


def test_configuration_error_inherits_zenith_error() -> None:
    assert issubclass(ConfigurationError, ZenithError)


def test_zenith_runtime_error_inherits_zenith_error() -> None:
    assert issubclass(ZenithRuntimeError, ZenithError)


def test_zenith_runtime_error_does_not_shadow_builtin() -> None:
    assert ZenithRuntimeError is not RuntimeError
    assert not issubclass(ZenithRuntimeError, RuntimeError)


def test_validation_error_inherits_zenith_error() -> None:
    assert issubclass(ValidationError, ZenithError)


def test_event_bus_error_inherits_zenith_error() -> None:
    assert issubclass(EventBusError, ZenithError)


def test_all_shared_errors_are_catchable_as_zenith_error() -> None:
    for error_type in (ConfigurationError, ZenithRuntimeError, ValidationError, EventBusError):
        try:
            raise error_type("boom")
        except ZenithError as exc:
            assert isinstance(exc, error_type)
