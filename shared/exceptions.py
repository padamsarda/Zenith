"""Generic exception hierarchy shared across Zenith and any future
platform built on it.

Only exceptions with no dependency on a specific runtime subsystem
belong here. Domain exceptions tied to the assistant runtime's
subsystems (service registry, event bus, commands, plugins) live in
`runtime.exceptions` instead, rooted at `ZenithError` below.
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
