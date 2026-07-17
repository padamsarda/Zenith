"""Concrete events emitted by the command execution framework."""

from __future__ import annotations

from dataclasses import dataclass

from runtime.events.event import Event


@dataclass(frozen=True)
class CommandCreated(Event):
    """Emitted when a Command enters the execution framework via `CommandExecutor.execute`."""


@dataclass(frozen=True)
class CommandStarted(Event):
    """Emitted when a CommandExecutor begins running a Command's action."""


@dataclass(frozen=True)
class CommandCompleted(Event):
    """Emitted when a Command's action finishes successfully."""


@dataclass(frozen=True)
class CommandFailed(Event):
    """Emitted when a Command fails validation or its action raises."""


@dataclass(frozen=True)
class CommandCancelled(Event):
    """Emitted when a Command's action raises CommandCancelledError."""
