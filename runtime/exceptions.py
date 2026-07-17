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
