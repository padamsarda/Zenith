"""Validation helpers for the Engineering Manager domain.

Mirrors `runtime.validation` and its siblings: small, explicit guard
functions that raise on failure rather than returning a boolean, used at
the boundaries of the domain (construction is unvalidated, mirroring
`Config`, `Command`, and `PluginManifest`; the facade and store validate
before acting).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from engineering_manager.domain.states import ProjectStatus, SessionStatus, TaskStatus
from engineering_manager.exceptions import DomainValidationError
from shared.utils.text_utils import is_blank_or_padded

if TYPE_CHECKING:
    from engineering_manager.domain.account import ProviderAccount
    from engineering_manager.domain.project import Project
    from engineering_manager.domain.session import Session
    from engineering_manager.domain.task import Task

_VALID_PROJECT_TRANSITIONS: dict[ProjectStatus, frozenset[ProjectStatus]] = {
    ProjectStatus.ACTIVE: frozenset({ProjectStatus.PAUSED, ProjectStatus.ARCHIVED}),
    ProjectStatus.PAUSED: frozenset({ProjectStatus.ACTIVE, ProjectStatus.ARCHIVED}),
    ProjectStatus.ARCHIVED: frozenset(),
}

# IN_PROGRESS deliberately cannot reach DONE directly: every completed
# piece of work passes through NEEDS_REVIEW, the human approval gate.
# IN_PROGRESS -> READY covers an abandoned session: the task itself is
# fine and goes back into the dispatchable pool.
_VALID_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.DRAFT: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.READY: frozenset(
        {TaskStatus.DRAFT, TaskStatus.IN_PROGRESS, TaskStatus.CANCELLED}
    ),
    TaskStatus.IN_PROGRESS: frozenset(
        {TaskStatus.NEEDS_REVIEW, TaskStatus.READY, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.NEEDS_REVIEW: frozenset(
        {TaskStatus.DONE, TaskStatus.READY, TaskStatus.CANCELLED}
    ),
    TaskStatus.FAILED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.DONE: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

_VALID_SESSION_TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.ACTIVE: frozenset(
        {
            SessionStatus.INTERRUPTED,
            SessionStatus.COMPLETED,
            SessionStatus.FAILED,
            SessionStatus.ABANDONED,
        }
    ),
    SessionStatus.INTERRUPTED: frozenset(
        {SessionStatus.ACTIVE, SessionStatus.FAILED, SessionStatus.ABANDONED}
    ),
    SessionStatus.COMPLETED: frozenset(),
    SessionStatus.FAILED: frozenset(),
    SessionStatus.ABANDONED: frozenset(),
}


def validate_project_status_transition(current: ProjectStatus, new: ProjectStatus) -> None:
    """Raise DomainValidationError if `current` -> `new` is not allowed for a project."""
    if new not in _VALID_PROJECT_TRANSITIONS[current]:
        raise DomainValidationError(
            f"Invalid project status transition: {current.name} -> {new.name}"
        )


def validate_task_status_transition(current: TaskStatus, new: TaskStatus) -> None:
    """Raise DomainValidationError if `current` -> `new` is not allowed for a task."""
    if new not in _VALID_TASK_TRANSITIONS[current]:
        raise DomainValidationError(
            f"Invalid task status transition: {current.name} -> {new.name}"
        )


def validate_session_status_transition(current: SessionStatus, new: SessionStatus) -> None:
    """Raise DomainValidationError if `current` -> `new` is not allowed for a session."""
    if new not in _VALID_SESSION_TRANSITIONS[current]:
        raise DomainValidationError(
            f"Invalid session status transition: {current.name} -> {new.name}"
        )


def validate_identifier(value: str, *, kind: str) -> None:
    """Raise DomainValidationError if `value` is not a usable identifier.

    A valid identifier is a non-empty string with no leading or trailing
    whitespace. `kind` names the identifier in the error message
    (e.g. "project id", "account id").
    """
    if is_blank_or_padded(value):
        raise DomainValidationError(f"Invalid {kind}: {value!r}")


def validate_priority(priority: int) -> None:
    """Raise DomainValidationError if `priority` is not a plain int.

    `bool` is rejected explicitly because it is a subclass of `int` and
    would silently pass an `isinstance` check.
    """
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise DomainValidationError(f"Task priority must be an int, got {priority!r}")


def validate_depends_on(depends_on: frozenset[UUID], task_id: UUID) -> None:
    """Raise DomainValidationError if `depends_on` is malformed.

    Checks that the dependency set is a `frozenset` of `UUID`s and does
    not contain the task's own ID. Whether each dependency exists (and
    belongs to the same project) is a cross-entity check performed by
    the facade, not here.
    """
    if not isinstance(depends_on, frozenset):
        raise DomainValidationError(
            f"Task depends_on must be a frozenset, got {type(depends_on).__name__}"
        )
    for dependency_id in depends_on:
        if not isinstance(dependency_id, UUID):
            raise DomainValidationError(
                f"Task dependencies must be UUIDs, got {dependency_id!r}"
            )
    if task_id in depends_on:
        raise DomainValidationError(f"Task {task_id} cannot depend on itself.")


def validate_project(project: Project) -> None:
    """Raise DomainValidationError if `project` fails structural validation."""
    validate_identifier(project.project_id, kind="project id")
    validate_identifier(project.name, kind="project name")
    if not isinstance(project.root_path, Path):
        raise DomainValidationError(
            f"Project root_path must be a Path, got {type(project.root_path).__name__}"
        )


def validate_task(task: Task) -> None:
    """Raise DomainValidationError if `task` fails structural validation."""
    validate_identifier(task.project_id, kind="project id")
    validate_identifier(task.title, kind="task title")
    validate_priority(task.priority)
    validate_depends_on(task.depends_on, task.task_id)


def validate_session(session: Session) -> None:
    """Raise DomainValidationError if `session` fails structural validation."""
    validate_identifier(session.project_id, kind="project id")
    validate_identifier(session.provider_id, kind="provider id")
    validate_identifier(session.account_id, kind="account id")


def validate_account(account: ProviderAccount) -> None:
    """Raise DomainValidationError if `account` fails structural validation."""
    validate_identifier(account.provider_id, kind="provider id")
    validate_identifier(account.account_id, kind="account id")
