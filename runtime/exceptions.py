"""Exception hierarchy for the Zenith assistant runtime's subsystems.

Covers the service registry, event bus, command execution framework,
and plugin framework. These are specific to how this runtime models
services, events, commands, and plugins, so they live here rather than
in `shared.exceptions` — a future platform built on `shared` would not
necessarily share these same abstractions. Every class here still
roots at `shared.exceptions.ZenithError`.
"""

from __future__ import annotations

from shared.exceptions import ZenithError


class ServiceRegistryError(ZenithError):
    """Base class for service registry errors."""


class ServiceNotFoundError(ServiceRegistryError):
    """Raised when looking up or removing a service that isn't registered."""


class ServiceAlreadyRegisteredError(ServiceRegistryError):
    """Raised when registering a service name that is already in use."""


class EventBusError(ZenithError):
    """Raised for invalid EventBus operations, such as unsubscribing a
    listener that was never subscribed to the given event type.
    """


class CommandError(ZenithError):
    """Base class for all command execution framework errors."""


class CommandValidationError(CommandError):
    """Raised when a Command fails validation.

    Covers structural issues (name, metadata), duplicate execution of an
    already-executed command ID, and invalid `CommandStatus` transitions.
    """


class CommandExecutionError(CommandError):
    """Raised by a command action to report a structured execution failure.

    The `CommandExecutor` treats this the same as any other exception
    raised from an action: it is caught, logged, and turned into a
    failed `CommandResult` rather than propagating.
    """


class CommandCancelledError(CommandError):
    """Raised by a command action to signal cooperative cancellation."""


class PluginError(ZenithError):
    """Base class for all plugin framework errors."""


class PluginRegistrationError(PluginError):
    """Raised when registering a plugin ID that is already registered."""


class PluginNotFoundError(PluginError):
    """Raised when looking up, unregistering, enabling, or disabling a
    plugin ID that isn't registered.
    """


class PluginValidationError(PluginError):
    """Raised when a Plugin fails validation.

    Covers structural issues (manifest fields, version format) and
    invalid `PluginState` transitions.
    """


class PluginLifecycleError(PluginError):
    """Raised when a Plugin's `initialize`, `shutdown`, `register`, or
    `unregister` hook raises during `PluginRegistry.register` or
    `PluginRegistry.unregister`. Wraps the original exception.
    """
