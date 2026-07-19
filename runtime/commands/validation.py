"""Validation helpers for the command execution framework.

Mirrors `runtime.validation`: small, explicit guard functions that raise
on failure rather than returning a boolean, used at the boundaries of the
command framework (command construction, status transitions, execution).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from runtime.commands.status import CommandStatus
from shared.exceptions import CommandValidationError
from shared.utils.text_utils import is_blank_or_padded

if TYPE_CHECKING:
    from runtime.commands.command import Command

_VALID_TRANSITIONS: dict[CommandStatus, frozenset[CommandStatus]] = {
    CommandStatus.CREATED: frozenset(
        {
            CommandStatus.QUEUED,
            CommandStatus.RUNNING,
            CommandStatus.FAILED,
            CommandStatus.CANCELLED,
        }
    ),
    CommandStatus.QUEUED: frozenset(
        {CommandStatus.RUNNING, CommandStatus.FAILED, CommandStatus.CANCELLED}
    ),
    CommandStatus.RUNNING: frozenset(
        {CommandStatus.COMPLETED, CommandStatus.FAILED, CommandStatus.CANCELLED}
    ),
    CommandStatus.COMPLETED: frozenset(),
    CommandStatus.FAILED: frozenset(),
    CommandStatus.CANCELLED: frozenset(),
}


def validate_status_transition(current: CommandStatus, new: CommandStatus) -> None:
    """Raise CommandValidationError if `current` -> `new` is not an allowed transition.

    Every status is reachable from `CREATED` except itself in reverse;
    `COMPLETED`, `FAILED`, and `CANCELLED` are terminal and accept no
    further transitions.
    """
    if new not in _VALID_TRANSITIONS[current]:
        raise CommandValidationError(
            f"Invalid command status transition: {current.name} -> {new.name}"
        )


def validate_command_name(name: str) -> None:
    """Raise CommandValidationError if `name` is not a usable command name.

    A valid command name is a non-empty string with no leading or
    trailing whitespace.
    """
    if is_blank_or_padded(name):
        raise CommandValidationError(f"Invalid command name: {name!r}")


def validate_command_metadata(metadata: dict[str, Any]) -> None:
    """Raise CommandValidationError if `metadata` is not a string-keyed dict."""
    if not isinstance(metadata, dict):
        raise CommandValidationError(
            f"Command metadata must be a dict, got {type(metadata).__name__}"
        )
    for key in metadata:
        if not isinstance(key, str):
            raise CommandValidationError(f"Command metadata keys must be strings, got {key!r}")


def validate_command(command: Command) -> None:
    """Raise CommandValidationError if `command` fails structural validation.

    Checks the command's name and metadata. Does not check for duplicate
    IDs — detecting a duplicate requires tracking commands across calls,
    which is the `CommandExecutor`'s responsibility, not a stateless
    validation function's.
    """
    validate_command_name(command.name)
    validate_command_metadata(command.metadata)
