"""Command lifecycle state definitions."""

from __future__ import annotations

from enum import Enum, auto


class CommandStatus(Enum):
    """Represents the lifecycle state of a Command.

    `QUEUED` is reserved for a future queuing system and is not entered
    by anything in this milestone; `CommandExecutor` moves a command
    directly from `CREATED` to `RUNNING`.
    """

    CREATED = auto()
    QUEUED = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


TERMINAL_STATUSES: frozenset[CommandStatus] = frozenset(
    {CommandStatus.COMPLETED, CommandStatus.FAILED, CommandStatus.CANCELLED}
)
