"""Command: an immutable description of a single action Zenith can execute."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from runtime.commands.status import CommandStatus
from runtime.commands.validation import validate_status_transition
from shared.utils.time_utils import utc_now
from shared.utils.uuid_utils import generate_id


@dataclass(frozen=True)
class Command:
    """A single, structured action for Zenith to execute.

    Every field is fixed at creation except `status`, which may only
    change through `transition_to` — direct assignment (`command.status
    = ...`) raises, like assigning to any other field on a frozen
    dataclass. Construction does not validate `name` or `metadata`; that
    happens at the framework boundary, in
    `runtime.commands.validation.validate_command`, mirroring how
    `configs.config.Config` is validated separately from construction.
    """

    name: str
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    command_id: UUID = field(default_factory=generate_id)
    created_at: datetime = field(default_factory=utc_now)
    status: CommandStatus = CommandStatus.CREATED

    def transition_to(self, new_status: CommandStatus) -> None:
        """Move this command to `new_status`.

        Raises:
            CommandValidationError: If the transition from the current
                status to `new_status` is not permitted.
        """
        validate_status_transition(self.status, new_status)
        object.__setattr__(self, "status", new_status)
