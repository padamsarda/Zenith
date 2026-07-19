"""Tests for the EngineeringManager facade."""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_manager.domain.states import ProjectStatus, SessionStatus, TaskStatus
from engineering_manager.events import TaskStatusChanged
from engineering_manager.exceptions import (
    DomainValidationError,
    DuplicateEntityError,
    ProjectNotFoundError,
    TaskNotFoundError,
)
from engineering_manager.manager import EngineeringManager
from engineering_manager.providers.in_memory import InMemoryProvider
from engineering_manager.store.store import Store
from shared.events.event import Event


@pytest.fixture
def manager(tmp_path: Path) -> EngineeringManager:
    manager = EngineeringManager(Store(tmp_path / "em.db"))
    manager.register_provider(InMemoryProvider())
    yield manager
    manager.close()


def test_add_project_persists_and_logs(manager: EngineeringManager, tmp_path: Path) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)

    assert manager.get_project("zenith").name == "Zenith"
    assert [entry.name for entry in manager.list_events()] == ["ProjectAdded"]


def test_add_project_with_invalid_id_raises(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    with pytest.raises(DomainValidationError):
        manager.add_project("  ", "Zenith", tmp_path)


def test_add_duplicate_project_raises(manager: EngineeringManager, tmp_path: Path) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)

    with pytest.raises(DuplicateEntityError):
        manager.add_project("zenith", "Zenith", tmp_path)


def test_set_project_status_pauses_project(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)

    manager.set_project_status("zenith", ProjectStatus.PAUSED)

    assert manager.get_project("zenith").status is ProjectStatus.PAUSED


def test_add_task_requires_existing_project(manager: EngineeringManager) -> None:
    with pytest.raises(ProjectNotFoundError):
        manager.add_task("missing", "Write docs")


def test_add_task_with_missing_dependency_raises(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    from uuid import uuid4

    manager.add_project("zenith", "Zenith", tmp_path)

    with pytest.raises(TaskNotFoundError):
        manager.add_task("zenith", "Write docs", depends_on=[uuid4()])


def test_add_task_with_cross_project_dependency_raises(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_project("other", "Other", tmp_path)
    foreign = manager.add_task("other", "Foreign work")

    with pytest.raises(DomainValidationError):
        manager.add_task("zenith", "Write docs", depends_on=[foreign.task_id])


def test_full_task_lifecycle_through_the_two_human_gates(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    task = manager.add_task("zenith", "Write docs", description="All of them")

    # Gate one: human approves the draft.
    manager.approve_task(task.task_id)
    assert manager.get_task(task.task_id).status is TaskStatus.READY

    # Autonomous stretch: dispatch and completion.
    session = manager.dispatch()
    assert session is not None
    assert manager.get_task(task.task_id).status is TaskStatus.IN_PROGRESS

    manager.complete_session(session.session_id, summary="Docs written.")
    assert manager.get_task(task.task_id).status is TaskStatus.NEEDS_REVIEW

    # Gate two: human accepts the work.
    manager.accept_task(task.task_id)
    assert manager.get_task(task.task_id).status is TaskStatus.DONE

    stored_session = manager.list_sessions(task_id=task.task_id)[0]
    assert stored_session.status is SessionStatus.COMPLETED
    assert stored_session.summary == "Docs written."


def test_draft_task_cannot_be_dispatched(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    manager.add_task("zenith", "Write docs")

    assert manager.dispatch() is None


def test_accept_task_before_review_raises(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    task = manager.add_task("zenith", "Write docs")

    with pytest.raises(DomainValidationError):
        manager.accept_task(task.task_id)


def test_rework_task_returns_it_to_ready(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    task = manager.add_task("zenith", "Write docs")
    manager.approve_task(task.task_id)
    session = manager.dispatch()
    manager.complete_session(session.session_id)

    manager.rework_task(task.task_id)

    assert manager.get_task(task.task_id).status is TaskStatus.READY


def test_retry_failed_task(manager: EngineeringManager, tmp_path: Path) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    task = manager.add_task("zenith", "Write docs")
    manager.approve_task(task.task_id)
    session = manager.dispatch()
    manager.fail_session(session.session_id, reason="crashed")
    assert manager.get_task(task.task_id).status is TaskStatus.FAILED

    manager.retry_task(task.task_id)

    assert manager.get_task(task.task_id).status is TaskStatus.READY


def test_revise_and_cancel_task(manager: EngineeringManager, tmp_path: Path) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    task = manager.add_task("zenith", "Write docs")
    manager.approve_task(task.task_id)

    manager.revise_task(task.task_id)
    assert manager.get_task(task.task_id).status is TaskStatus.DRAFT

    manager.cancel_task(task.task_id)
    assert manager.get_task(task.task_id).status is TaskStatus.CANCELLED


def test_dependent_task_dispatches_only_after_dependency_done(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    dependency = manager.add_task("zenith", "Foundation")
    dependent = manager.add_task(
        "zenith", "Building", depends_on=[dependency.task_id], priority=10
    )
    manager.approve_task(dependency.task_id)
    manager.approve_task(dependent.task_id)

    # Despite lower priority, the dependency dispatches first.
    first = manager.dispatch()
    assert first.task_id == dependency.task_id

    manager.complete_session(first.session_id)
    manager.accept_task(dependency.task_id)

    second = manager.dispatch()
    assert second.task_id == dependent.task_id


def test_account_add_remove_and_events(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_account("in-memory", "personal", label="Personal")
    assert len(manager.list_accounts()) == 1

    manager.remove_account("in-memory", "personal")
    assert manager.list_accounts() == []

    names = [entry.name for entry in manager.list_events()]
    assert names == ["AccountRemoved", "AccountAdded"]


def test_facade_events_reach_bus_subscribers(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    received: list[Event] = []
    manager.events.subscribe(TaskStatusChanged, received.append)
    manager.add_project("zenith", "Zenith", tmp_path)
    task = manager.add_task("zenith", "Write docs")

    manager.approve_task(task.task_id)

    assert len(received) == 1
    assert received[0].payload["to"] == "READY"


def test_event_log_tells_the_whole_story(
    manager: EngineeringManager, tmp_path: Path
) -> None:
    manager.add_project("zenith", "Zenith", tmp_path)
    manager.add_account("in-memory", "personal")
    task = manager.add_task("zenith", "Write docs")
    manager.approve_task(task.task_id)
    session = manager.dispatch()
    manager.complete_session(session.session_id)
    manager.accept_task(task.task_id)

    names = [entry.name for entry in manager.list_events()]
    assert names == [
        "TaskStatusChanged",  # NEEDS_REVIEW -> DONE
        "TaskStatusChanged",  # IN_PROGRESS -> NEEDS_REVIEW
        "SessionStatusChanged",  # ACTIVE -> COMPLETED
        "SessionStarted",
        "TaskStatusChanged",  # READY -> IN_PROGRESS
        "TaskStatusChanged",  # DRAFT -> READY
        "TaskAdded",
        "AccountAdded",
        "ProjectAdded",
    ]
