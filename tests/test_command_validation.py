"""Tests for runtime.commands.validation helpers."""

from __future__ import annotations

import pytest

from runtime.commands.command import Command
from runtime.commands.status import CommandStatus
from runtime.commands.validation import (
    validate_command,
    validate_command_metadata,
    validate_command_name,
    validate_status_transition,
)
from runtime.exceptions import CommandValidationError


@pytest.mark.parametrize("name", ["do-thing", "do_thing", "do thing 1"])
def test_validate_command_name_accepts_valid_names(name: str) -> None:
    validate_command_name(name)


@pytest.mark.parametrize("name", ["", "   ", " padded", "padded "])
def test_validate_command_name_rejects_invalid_names(name: str) -> None:
    with pytest.raises(CommandValidationError):
        validate_command_name(name)


def test_validate_command_name_rejects_non_string() -> None:
    with pytest.raises(CommandValidationError):
        validate_command_name(123)  # type: ignore[arg-type]


def test_validate_command_metadata_accepts_empty_dict() -> None:
    validate_command_metadata({})


def test_validate_command_metadata_accepts_string_keyed_dict() -> None:
    validate_command_metadata({"a": 1, "b": "two"})


def test_validate_command_metadata_rejects_non_dict() -> None:
    with pytest.raises(CommandValidationError):
        validate_command_metadata(["not", "a", "dict"])  # type: ignore[arg-type]


def test_validate_command_metadata_rejects_non_string_key() -> None:
    with pytest.raises(CommandValidationError):
        validate_command_metadata({1: "value"})  # type: ignore[dict-item]


def test_validate_command_passes_for_valid_command() -> None:
    validate_command(Command(name="test"))


def test_validate_command_rejects_invalid_name() -> None:
    with pytest.raises(CommandValidationError):
        validate_command(Command(name=""))


def test_validate_command_rejects_invalid_metadata() -> None:
    command = Command(name="test", metadata="not-a-dict")  # type: ignore[arg-type]

    with pytest.raises(CommandValidationError):
        validate_command(command)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (CommandStatus.CREATED, CommandStatus.QUEUED),
        (CommandStatus.CREATED, CommandStatus.RUNNING),
        (CommandStatus.CREATED, CommandStatus.FAILED),
        (CommandStatus.CREATED, CommandStatus.CANCELLED),
        (CommandStatus.QUEUED, CommandStatus.RUNNING),
        (CommandStatus.QUEUED, CommandStatus.FAILED),
        (CommandStatus.QUEUED, CommandStatus.CANCELLED),
        (CommandStatus.RUNNING, CommandStatus.COMPLETED),
        (CommandStatus.RUNNING, CommandStatus.FAILED),
        (CommandStatus.RUNNING, CommandStatus.CANCELLED),
    ],
)
def test_validate_status_transition_accepts_valid_transitions(
    current: CommandStatus, new: CommandStatus
) -> None:
    validate_status_transition(current, new)


@pytest.mark.parametrize(
    ("current", "new"),
    [
        (CommandStatus.CREATED, CommandStatus.COMPLETED),
        (CommandStatus.QUEUED, CommandStatus.COMPLETED),
        (CommandStatus.RUNNING, CommandStatus.QUEUED),
        (CommandStatus.COMPLETED, CommandStatus.RUNNING),
        (CommandStatus.FAILED, CommandStatus.RUNNING),
        (CommandStatus.CANCELLED, CommandStatus.RUNNING),
        (CommandStatus.CREATED, CommandStatus.CREATED),
    ],
)
def test_validate_status_transition_rejects_invalid_transitions(
    current: CommandStatus, new: CommandStatus
) -> None:
    with pytest.raises(CommandValidationError):
        validate_status_transition(current, new)
