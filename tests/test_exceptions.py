"""Tests for the Zenith exception hierarchy."""

from __future__ import annotations

from runtime.exceptions import ConfigurationError, ZenithError, ZenithRuntimeError


def test_zenith_error_is_an_exception() -> None:
    assert issubclass(ZenithError, Exception)


def test_configuration_error_inherits_zenith_error() -> None:
    assert issubclass(ConfigurationError, ZenithError)


def test_zenith_runtime_error_inherits_zenith_error() -> None:
    assert issubclass(ZenithRuntimeError, ZenithError)


def test_zenith_runtime_error_does_not_shadow_builtin() -> None:
    assert ZenithRuntimeError is not RuntimeError
    assert not issubclass(ZenithRuntimeError, RuntimeError)
