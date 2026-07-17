"""Runtime lifecycle state definitions."""

from __future__ import annotations

from enum import Enum, auto


class RuntimeState(Enum):
    """Represents the lifecycle state of the Zenith runtime."""

    INITIALIZING = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()
    FAILED = auto()
