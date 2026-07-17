"""Tests for the CommandStatus enum."""

from __future__ import annotations

from runtime.commands.status import TERMINAL_STATUSES, CommandStatus


def test_expected_statuses_exist() -> None:
    expected_names = {
        "CREATED",
        "QUEUED",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    }

    assert {status.name for status in CommandStatus} == expected_names


def test_statuses_have_distinct_values() -> None:
    values = [status.value for status in CommandStatus]

    assert len(values) == len(set(values))


def test_terminal_statuses_contains_completed() -> None:
    assert CommandStatus.COMPLETED in TERMINAL_STATUSES


def test_terminal_statuses_contains_failed() -> None:
    assert CommandStatus.FAILED in TERMINAL_STATUSES


def test_terminal_statuses_contains_cancelled() -> None:
    assert CommandStatus.CANCELLED in TERMINAL_STATUSES


def test_terminal_statuses_excludes_created() -> None:
    assert CommandStatus.CREATED not in TERMINAL_STATUSES


def test_terminal_statuses_excludes_queued() -> None:
    assert CommandStatus.QUEUED not in TERMINAL_STATUSES


def test_terminal_statuses_excludes_running() -> None:
    assert CommandStatus.RUNNING not in TERMINAL_STATUSES


def test_terminal_statuses_has_exactly_three_members() -> None:
    assert len(TERMINAL_STATUSES) == 3
