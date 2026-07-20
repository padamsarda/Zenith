"""Tests for the Engineering Manager domain state enums."""

from __future__ import annotations

from engineering_manager.domain.states import (
    TERMINAL_PLAN_STATUSES,
    TERMINAL_PROJECT_STATUSES,
    TERMINAL_SESSION_STATUSES,
    TERMINAL_TASK_STATUSES,
    PlanStatus,
    ProjectStatus,
    SessionStatus,
    TaskStatus,
)


def test_project_status_members() -> None:
    assert {status.name for status in ProjectStatus} == {"ACTIVE", "PAUSED", "ARCHIVED"}


def test_plan_status_members() -> None:
    assert {status.name for status in PlanStatus} == {
        "DRAFT",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
    }


def test_task_status_members() -> None:
    assert {status.name for status in TaskStatus} == {
        "DRAFT",
        "READY",
        "IN_PROGRESS",
        "NEEDS_REVIEW",
        "DONE",
        "FAILED",
        "CANCELLED",
    }


def test_session_status_members() -> None:
    assert {status.name for status in SessionStatus} == {
        "ACTIVE",
        "INTERRUPTED",
        "COMPLETED",
        "FAILED",
        "ABANDONED",
    }


def test_archived_is_the_only_terminal_project_status() -> None:
    assert TERMINAL_PROJECT_STATUSES == frozenset({ProjectStatus.ARCHIVED})


def test_completed_and_cancelled_are_terminal_plan_statuses() -> None:
    assert TERMINAL_PLAN_STATUSES == frozenset(
        {PlanStatus.COMPLETED, PlanStatus.CANCELLED}
    )


def test_done_and_cancelled_are_terminal_task_statuses() -> None:
    assert TERMINAL_TASK_STATUSES == frozenset({TaskStatus.DONE, TaskStatus.CANCELLED})


def test_failed_task_status_is_not_terminal() -> None:
    assert TaskStatus.FAILED not in TERMINAL_TASK_STATUSES


def test_completed_failed_abandoned_are_terminal_session_statuses() -> None:
    assert TERMINAL_SESSION_STATUSES == frozenset(
        {SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.ABANDONED}
    )
