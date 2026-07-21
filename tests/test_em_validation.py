"""Tests for the Engineering Manager domain validation guards."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.plan import Plan
from engineering_manager.domain.project import Project
from engineering_manager.domain.session import Session
from engineering_manager.domain.states import (
    PlanStatus,
    ProjectStatus,
    SessionStatus,
    TaskStatus,
)
from engineering_manager.domain.task import Task
from engineering_manager.domain.validation import (
    validate_account,
    validate_dependency_addition,
    validate_depends_on,
    validate_identifier,
    validate_plan,
    validate_plan_status_transition,
    validate_priority,
    validate_project,
    validate_project_status_transition,
    validate_resume_at,
    validate_revision,
    validate_session,
    validate_session_status_transition,
    validate_task,
    validate_task_status_transition,
)
from engineering_manager.exceptions import DomainValidationError


def test_active_project_can_pause_and_archive() -> None:
    validate_project_status_transition(ProjectStatus.ACTIVE, ProjectStatus.PAUSED)
    validate_project_status_transition(ProjectStatus.ACTIVE, ProjectStatus.ARCHIVED)


def test_paused_project_can_resume() -> None:
    validate_project_status_transition(ProjectStatus.PAUSED, ProjectStatus.ACTIVE)


def test_archived_project_accepts_no_transition() -> None:
    for new in ProjectStatus:
        with pytest.raises(DomainValidationError):
            validate_project_status_transition(ProjectStatus.ARCHIVED, new)


def test_draft_plan_can_start_or_cancel() -> None:
    validate_plan_status_transition(PlanStatus.DRAFT, PlanStatus.IN_PROGRESS)
    validate_plan_status_transition(PlanStatus.DRAFT, PlanStatus.CANCELLED)


def test_draft_plan_cannot_complete_directly() -> None:
    with pytest.raises(DomainValidationError):
        validate_plan_status_transition(PlanStatus.DRAFT, PlanStatus.COMPLETED)


def test_in_progress_plan_can_complete_or_cancel() -> None:
    validate_plan_status_transition(PlanStatus.IN_PROGRESS, PlanStatus.COMPLETED)
    validate_plan_status_transition(PlanStatus.IN_PROGRESS, PlanStatus.CANCELLED)


def test_terminal_plans_accept_no_transition() -> None:
    for terminal in (PlanStatus.COMPLETED, PlanStatus.CANCELLED):
        for new in PlanStatus:
            with pytest.raises(DomainValidationError):
                validate_plan_status_transition(terminal, new)


def test_draft_task_can_become_ready_or_cancelled() -> None:
    validate_task_status_transition(TaskStatus.DRAFT, TaskStatus.READY)
    validate_task_status_transition(TaskStatus.DRAFT, TaskStatus.CANCELLED)


def test_draft_task_cannot_start_directly() -> None:
    with pytest.raises(DomainValidationError):
        validate_task_status_transition(TaskStatus.DRAFT, TaskStatus.IN_PROGRESS)


def test_in_progress_task_cannot_skip_review() -> None:
    with pytest.raises(DomainValidationError):
        validate_task_status_transition(TaskStatus.IN_PROGRESS, TaskStatus.DONE)


def test_in_progress_task_can_return_to_ready() -> None:
    validate_task_status_transition(TaskStatus.IN_PROGRESS, TaskStatus.READY)


def test_needs_review_task_can_be_accepted_or_sent_back() -> None:
    validate_task_status_transition(TaskStatus.NEEDS_REVIEW, TaskStatus.DONE)
    validate_task_status_transition(TaskStatus.NEEDS_REVIEW, TaskStatus.READY)


def test_failed_task_can_be_retried() -> None:
    validate_task_status_transition(TaskStatus.FAILED, TaskStatus.READY)


def test_done_and_cancelled_tasks_accept_no_transition() -> None:
    for terminal in (TaskStatus.DONE, TaskStatus.CANCELLED):
        for new in TaskStatus:
            with pytest.raises(DomainValidationError):
                validate_task_status_transition(terminal, new)


def test_active_session_can_reach_every_other_status() -> None:
    for new in (
        SessionStatus.INTERRUPTED,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.ABANDONED,
    ):
        validate_session_status_transition(SessionStatus.ACTIVE, new)


def test_interrupted_session_can_resume() -> None:
    validate_session_status_transition(SessionStatus.INTERRUPTED, SessionStatus.ACTIVE)


def test_interrupted_session_cannot_complete_directly() -> None:
    with pytest.raises(DomainValidationError):
        validate_session_status_transition(SessionStatus.INTERRUPTED, SessionStatus.COMPLETED)


def test_terminal_sessions_accept_no_transition() -> None:
    for terminal in (SessionStatus.COMPLETED, SessionStatus.FAILED, SessionStatus.ABANDONED):
        for new in SessionStatus:
            with pytest.raises(DomainValidationError):
                validate_session_status_transition(terminal, new)


def test_validate_identifier_accepts_plain_string() -> None:
    validate_identifier("zenith", kind="project id")


@pytest.mark.parametrize("value", ["", "   ", " padded ", 42, None])
def test_validate_identifier_rejects_blank_padded_or_non_string(value: object) -> None:
    with pytest.raises(DomainValidationError):
        validate_identifier(value, kind="project id")  # type: ignore[arg-type]


def test_validate_priority_accepts_int() -> None:
    validate_priority(0)
    validate_priority(-5)
    validate_priority(100)


@pytest.mark.parametrize("value", [True, False, 1.5, "high", None])
def test_validate_priority_rejects_non_int(value: object) -> None:
    with pytest.raises(DomainValidationError):
        validate_priority(value)  # type: ignore[arg-type]


def test_validate_depends_on_accepts_uuid_frozenset() -> None:
    validate_depends_on(frozenset({uuid4(), uuid4()}), uuid4())


def test_validate_depends_on_rejects_non_frozenset() -> None:
    with pytest.raises(DomainValidationError):
        validate_depends_on([uuid4()], uuid4())  # type: ignore[arg-type]


def test_validate_depends_on_rejects_non_uuid_members() -> None:
    with pytest.raises(DomainValidationError):
        validate_depends_on(frozenset({"not-a-uuid"}), uuid4())  # type: ignore[arg-type]


def test_validate_depends_on_rejects_self_dependency() -> None:
    task_id = uuid4()
    with pytest.raises(DomainValidationError):
        validate_depends_on(frozenset({task_id}), task_id)


def test_validate_dependency_addition_accepts_new_uuid_on_draft_task() -> None:
    validate_dependency_addition(Task(project_id="zenith", title="Work"), uuid4())


def test_validate_dependency_addition_rejects_non_uuid() -> None:
    with pytest.raises(DomainValidationError):
        validate_dependency_addition(
            Task(project_id="zenith", title="Work"), "not-a-uuid"  # type: ignore[arg-type]
        )


def test_validate_dependency_addition_rejects_self() -> None:
    task = Task(project_id="zenith", title="Work")
    with pytest.raises(DomainValidationError):
        validate_dependency_addition(task, task.task_id)


def test_validate_dependency_addition_rejects_duplicate() -> None:
    dependency_id = uuid4()
    task = Task(project_id="zenith", title="Work", depends_on=frozenset({dependency_id}))
    with pytest.raises(DomainValidationError):
        validate_dependency_addition(task, dependency_id)


@pytest.mark.parametrize(
    "status",
    [TaskStatus.IN_PROGRESS, TaskStatus.NEEDS_REVIEW, TaskStatus.DONE, TaskStatus.CANCELLED],
)
def test_validate_dependency_addition_rejects_unschedulable_statuses(
    status: TaskStatus,
) -> None:
    task = Task(project_id="zenith", title="Work", status=status)
    with pytest.raises(DomainValidationError):
        validate_dependency_addition(task, uuid4())


@pytest.mark.parametrize(
    "status", [TaskStatus.DRAFT, TaskStatus.READY, TaskStatus.FAILED]
)
def test_validate_dependency_addition_accepts_schedulable_statuses(
    status: TaskStatus,
) -> None:
    validate_dependency_addition(
        Task(project_id="zenith", title="Work", status=status), uuid4()
    )


def test_validate_resume_at_accepts_datetime_and_none() -> None:
    validate_resume_at(datetime(2026, 7, 20, tzinfo=timezone.utc))
    validate_resume_at(None)


def test_validate_resume_at_rejects_other_types() -> None:
    with pytest.raises(DomainValidationError):
        validate_resume_at("2026-07-20T00:00:00")


def test_validate_revision_accepts_any_string() -> None:
    validate_revision("abc123", kind="starting revision")
    validate_revision("", kind="starting revision")


def test_validate_revision_rejects_non_strings() -> None:
    with pytest.raises(DomainValidationError):
        validate_revision(None, kind="ending revision")
    with pytest.raises(DomainValidationError):
        validate_revision(42, kind="ending revision")


def test_validate_revision_names_the_field_in_the_message() -> None:
    with pytest.raises(DomainValidationError, match="ending revision"):
        validate_revision(42, kind="ending revision")


def test_validate_project_accepts_well_formed_project(tmp_path: Path) -> None:
    validate_project(Project(project_id="zenith", name="Zenith", root_path=tmp_path))


def test_validate_project_rejects_bad_id(tmp_path: Path) -> None:
    with pytest.raises(DomainValidationError):
        validate_project(Project(project_id=" ", name="Zenith", root_path=tmp_path))


def test_validate_project_rejects_non_path_root(tmp_path: Path) -> None:
    with pytest.raises(DomainValidationError):
        validate_project(
            Project(project_id="zenith", name="Zenith", root_path=str(tmp_path))  # type: ignore[arg-type]
        )


def test_validate_plan_accepts_well_formed_plan() -> None:
    validate_plan(Plan(project_id="zenith", goal="Ship plugins"))


def test_validate_plan_rejects_blank_goal() -> None:
    with pytest.raises(DomainValidationError):
        validate_plan(Plan(project_id="zenith", goal="  "))


def test_validate_task_accepts_well_formed_task() -> None:
    validate_task(Task(project_id="zenith", title="Write docs"))


def test_validate_task_rejects_blank_title() -> None:
    with pytest.raises(DomainValidationError):
        validate_task(Task(project_id="zenith", title="  "))


def test_validate_session_accepts_well_formed_session() -> None:
    validate_session(
        Session(
            task_id=uuid4(), project_id="zenith", provider_id="claude", account_id="personal"
        )
    )


def test_validate_session_rejects_blank_provider() -> None:
    with pytest.raises(DomainValidationError):
        validate_session(
            Session(task_id=uuid4(), project_id="zenith", provider_id="", account_id="a")
        )


def test_validate_account_accepts_well_formed_account() -> None:
    validate_account(ProviderAccount(provider_id="claude", account_id="personal"))


def test_validate_account_rejects_blank_account_id() -> None:
    with pytest.raises(DomainValidationError):
        validate_account(ProviderAccount(provider_id="claude", account_id=" "))
