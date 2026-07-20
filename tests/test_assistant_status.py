"""Tests for the RequestStatus enum."""

from __future__ import annotations

from runtime.assistant.status import TERMINAL_STATUSES, RequestStatus


def test_expected_statuses_exist() -> None:
    expected_names = {"RECEIVED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}

    assert {status.name for status in RequestStatus} == expected_names


def test_statuses_have_distinct_values() -> None:
    values = [status.value for status in RequestStatus]

    assert len(values) == len(set(values))


def test_terminal_statuses_contains_completed() -> None:
    assert RequestStatus.COMPLETED in TERMINAL_STATUSES


def test_terminal_statuses_contains_failed() -> None:
    assert RequestStatus.FAILED in TERMINAL_STATUSES


def test_terminal_statuses_contains_cancelled() -> None:
    assert RequestStatus.CANCELLED in TERMINAL_STATUSES


def test_terminal_statuses_excludes_received() -> None:
    assert RequestStatus.RECEIVED not in TERMINAL_STATUSES


def test_terminal_statuses_excludes_running() -> None:
    assert RequestStatus.RUNNING not in TERMINAL_STATUSES


def test_terminal_statuses_has_exactly_three_members() -> None:
    assert len(TERMINAL_STATUSES) == 3
