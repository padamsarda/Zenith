"""Tests for the Command dataclass."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from runtime.commands.command import Command
from runtime.commands.status import CommandStatus
from runtime.exceptions import CommandValidationError


def test_command_has_uuid_id() -> None:
    command = Command(name="test")

    assert isinstance(command.command_id, UUID)


def test_two_commands_have_different_ids() -> None:
    first = Command(name="test")
    second = Command(name="test")

    assert first.command_id != second.command_id


def test_command_has_timezone_aware_timestamp() -> None:
    command = Command(name="test")

    assert isinstance(command.created_at, datetime)
    assert command.created_at.tzinfo == timezone.utc


def test_command_description_defaults_to_none() -> None:
    command = Command(name="test")

    assert command.description is None


def test_command_description_can_be_set() -> None:
    command = Command(name="test", description="does a thing")

    assert command.description == "does a thing"


def test_command_metadata_defaults_to_empty_dict() -> None:
    command = Command(name="test")

    assert command.metadata == {}


def test_command_metadata_can_carry_data() -> None:
    command = Command(name="test", metadata={"key": "value"})

    assert command.metadata == {"key": "value"}


def test_two_commands_have_independent_metadata() -> None:
    first = Command(name="test", metadata={"a": 1})
    second = Command(name="test")

    assert second.metadata == {}


def test_command_status_defaults_to_created() -> None:
    command = Command(name="test")

    assert command.status is CommandStatus.CREATED


def test_command_name_cannot_be_reassigned() -> None:
    command = Command(name="test")

    with pytest.raises(AttributeError):
        command.name = "other"  # type: ignore[misc]


def test_command_id_cannot_be_reassigned() -> None:
    command = Command(name="test")

    with pytest.raises(AttributeError):
        command.command_id = None  # type: ignore[misc]


def test_command_status_cannot_be_directly_assigned() -> None:
    command = Command(name="test")

    with pytest.raises(AttributeError):
        command.status = CommandStatus.RUNNING  # type: ignore[misc]


def test_transition_to_running_from_created_succeeds() -> None:
    command = Command(name="test")

    command.transition_to(CommandStatus.RUNNING)

    assert command.status is CommandStatus.RUNNING


def test_transition_to_completed_from_running_succeeds() -> None:
    command = Command(name="test")
    command.transition_to(CommandStatus.RUNNING)

    command.transition_to(CommandStatus.COMPLETED)

    assert command.status is CommandStatus.COMPLETED


def test_transition_to_failed_from_running_succeeds() -> None:
    command = Command(name="test")
    command.transition_to(CommandStatus.RUNNING)

    command.transition_to(CommandStatus.FAILED)

    assert command.status is CommandStatus.FAILED


def test_transition_to_cancelled_from_running_succeeds() -> None:
    command = Command(name="test")
    command.transition_to(CommandStatus.RUNNING)

    command.transition_to(CommandStatus.CANCELLED)

    assert command.status is CommandStatus.CANCELLED


def test_transition_to_failed_directly_from_created_succeeds() -> None:
    command = Command(name="test")

    command.transition_to(CommandStatus.FAILED)

    assert command.status is CommandStatus.FAILED


def test_transition_from_completed_raises() -> None:
    command = Command(name="test")
    command.transition_to(CommandStatus.RUNNING)
    command.transition_to(CommandStatus.COMPLETED)

    with pytest.raises(CommandValidationError):
        command.transition_to(CommandStatus.RUNNING)


def test_transition_from_failed_raises() -> None:
    command = Command(name="test")
    command.transition_to(CommandStatus.FAILED)

    with pytest.raises(CommandValidationError):
        command.transition_to(CommandStatus.COMPLETED)


def test_transition_from_cancelled_raises() -> None:
    command = Command(name="test")
    command.transition_to(CommandStatus.CANCELLED)

    with pytest.raises(CommandValidationError):
        command.transition_to(CommandStatus.RUNNING)


def test_invalid_transition_leaves_status_unchanged() -> None:
    command = Command(name="test")
    command.transition_to(CommandStatus.RUNNING)
    command.transition_to(CommandStatus.COMPLETED)

    with pytest.raises(CommandValidationError):
        command.transition_to(CommandStatus.FAILED)

    assert command.status is CommandStatus.COMPLETED


def test_transition_to_same_status_raises() -> None:
    command = Command(name="test")

    with pytest.raises(CommandValidationError):
        command.transition_to(CommandStatus.CREATED)


def test_construction_does_not_validate_name() -> None:
    command = Command(name="")

    assert command.name == ""


def test_construction_does_not_validate_metadata_type() -> None:
    command = Command(name="test", metadata="not-a-dict")  # type: ignore[arg-type]

    assert command.metadata == "not-a-dict"
