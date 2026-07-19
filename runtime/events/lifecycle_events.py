"""Concrete events emitted by the Zenith runtime lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from shared.events.event import Event


@dataclass(frozen=True)
class ApplicationStarting(Event):
    """Emitted when the runtime begins startup."""


@dataclass(frozen=True)
class ApplicationStarted(Event):
    """Emitted once the runtime has finished startup and is running."""


@dataclass(frozen=True)
class ApplicationStopping(Event):
    """Emitted when the runtime begins shutdown."""


@dataclass(frozen=True)
class ApplicationStopped(Event):
    """Emitted once the runtime has finished shutdown."""


@dataclass(frozen=True)
class ApplicationStartupFailed(Event):
    """Emitted when startup fails for a reason other than configuration."""


@dataclass(frozen=True)
class ConfigurationLoaded(Event):
    """Emitted after configuration has been successfully loaded."""


@dataclass(frozen=True)
class ConfigurationLoadFailed(Event):
    """Emitted when configuration loading fails."""
