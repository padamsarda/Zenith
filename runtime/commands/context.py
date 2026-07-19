"""CommandContext: per-execution context passed to a command's action."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from shared.utils.time_utils import utc_now

if TYPE_CHECKING:
    from runtime.context import ApplicationContext


@dataclass(frozen=True)
class CancellationToken:
    """Placeholder for future cooperative command cancellation.

    Carries no cancellation mechanism yet — there is nothing in this
    milestone that flips `cancelled`. It exists so `CommandContext` and
    future action implementations have a stable field to check once
    cancellation is actually wired up, without a breaking change later.
    """

    cancelled: bool = False


@dataclass(frozen=True)
class CommandContext:
    """Per-execution context passed to a command's action.

    Bundles the shared `ApplicationContext` with everything specific to
    one execution: when it started, which command it belongs to, a
    cancellation token placeholder, and execution-scoped metadata. Built
    fresh by `CommandExecutor` for each `execute` call — never shared
    across commands, and holds no global state.
    """

    application_context: ApplicationContext
    command_id: UUID
    started_at: datetime = field(default_factory=utc_now)
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)
    metadata: dict[str, Any] = field(default_factory=dict)
