"""Custom exception hierarchy for Zenith.

All Zenith-specific errors inherit from `ZenithError`. Future modules
should raise subclasses of this hierarchy rather than bare built-in
exceptions.
"""

from __future__ import annotations


class ZenithError(Exception):
    """Base class for all Zenith-specific errors."""


class ConfigurationError(ZenithError):
    """Raised when configuration loading or parsing fails."""


class ZenithRuntimeError(ZenithError):
    """Raised when the runtime encounters a lifecycle error.

    Named `ZenithRuntimeError` (not `RuntimeError`) to avoid shadowing
    Python's built-in `RuntimeError`.
    """


class ValidationError(ZenithError):
    """Raised when a value fails a validation check."""


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
