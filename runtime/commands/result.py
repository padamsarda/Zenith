"""CommandResult: the outcome of executing a single Command."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    """The outcome of executing a Command.

    A `CommandExecutor` always returns a `CommandResult` — whether the
    command succeeded, failed validation, raised, or was cancelled —
    never `None`.
    """

    success: bool
    message: str
    duration_seconds: float
    data: Any = None
    exception: BaseException | None = None
