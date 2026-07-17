"""Plugin lifecycle state definitions."""

from __future__ import annotations

from enum import Enum, auto


class PluginState(Enum):
    """Represents the lifecycle state of a Plugin.

    `CREATED -> INITIALIZED -> REGISTERED -> ENABLED <-> DISABLED`, with
    `STOPPED` reachable once a plugin has been initialized and `FAILED`
    reachable from any non-terminal state. `STOPPED` and `FAILED` are
    terminal — see `TERMINAL_STATES`.
    """

    CREATED = auto()
    INITIALIZED = auto()
    REGISTERED = auto()
    ENABLED = auto()
    DISABLED = auto()
    STOPPED = auto()
    FAILED = auto()


TERMINAL_STATES: frozenset[PluginState] = frozenset({PluginState.STOPPED, PluginState.FAILED})
