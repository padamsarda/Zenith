"""Tests for the runtime's domain-specific exception hierarchy."""

from __future__ import annotations

from runtime.exceptions import (
    CommandCancelledError,
    CommandError,
    CommandExecutionError,
    CommandValidationError,
    PluginError,
    PluginLifecycleError,
    PluginNotFoundError,
    PluginRegistrationError,
    PluginValidationError,
    ServiceAlreadyRegisteredError,
    ServiceNotFoundError,
    ServiceRegistryError,
)
from shared.exceptions import ZenithError


def test_service_registry_error_inherits_zenith_error() -> None:
    assert issubclass(ServiceRegistryError, ZenithError)


def test_service_not_found_error_inherits_service_registry_error() -> None:
    assert issubclass(ServiceNotFoundError, ServiceRegistryError)


def test_service_already_registered_error_inherits_service_registry_error() -> None:
    assert issubclass(ServiceAlreadyRegisteredError, ServiceRegistryError)


def test_command_error_inherits_zenith_error() -> None:
    assert issubclass(CommandError, ZenithError)


def test_command_validation_error_inherits_command_error() -> None:
    assert issubclass(CommandValidationError, CommandError)


def test_command_execution_error_inherits_command_error() -> None:
    assert issubclass(CommandExecutionError, CommandError)


def test_command_cancelled_error_inherits_command_error() -> None:
    assert issubclass(CommandCancelledError, CommandError)


def test_plugin_error_inherits_zenith_error() -> None:
    assert issubclass(PluginError, ZenithError)


def test_plugin_registration_error_inherits_plugin_error() -> None:
    assert issubclass(PluginRegistrationError, PluginError)


def test_plugin_not_found_error_inherits_plugin_error() -> None:
    assert issubclass(PluginNotFoundError, PluginError)


def test_plugin_validation_error_inherits_plugin_error() -> None:
    assert issubclass(PluginValidationError, PluginError)


def test_plugin_lifecycle_error_inherits_plugin_error() -> None:
    assert issubclass(PluginLifecycleError, PluginError)


def test_all_runtime_errors_are_catchable_as_zenith_error() -> None:
    for error_type in (
        ServiceRegistryError,
        ServiceNotFoundError,
        ServiceAlreadyRegisteredError,
        CommandError,
        CommandValidationError,
        CommandExecutionError,
        CommandCancelledError,
        PluginError,
        PluginRegistrationError,
        PluginNotFoundError,
        PluginValidationError,
        PluginLifecycleError,
    ):
        try:
            raise error_type("boom")
        except ZenithError as exc:
            assert isinstance(exc, error_type)


def test_all_command_errors_are_catchable_as_command_error() -> None:
    for error_type in (CommandValidationError, CommandExecutionError, CommandCancelledError):
        try:
            raise error_type("boom")
        except CommandError as exc:
            assert isinstance(exc, error_type)


def test_all_plugin_errors_are_catchable_as_plugin_error() -> None:
    for error_type in (
        PluginRegistrationError,
        PluginNotFoundError,
        PluginValidationError,
        PluginLifecycleError,
    ):
        try:
            raise error_type("boom")
        except PluginError as exc:
            assert isinstance(exc, error_type)
