"""Tests for the SQLite-backed Store."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.project import Project
from engineering_manager.domain.session import Session
from engineering_manager.domain.states import ProjectStatus, SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.events import ProjectAdded, TaskAdded
from engineering_manager.exceptions import (
    AccountNotFoundError,
    DuplicateEntityError,
    ProjectNotFoundError,
    SessionNotFoundError,
    StoreError,
    TaskNotFoundError,
)
from engineering_manager.store.store import Store


@pytest.fixture
def store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "em.db")
    yield store
    store.close()


def make_project(tmp_path: Path, project_id: str = "zenith") -> Project:
    return Project(project_id=project_id, name="Zenith", root_path=tmp_path)


def test_add_and_get_project(store: Store, tmp_path: Path) -> None:
    project = make_project(tmp_path)

    store.add_project(project)

    assert store.get_project("zenith") == project


def test_add_duplicate_project_raises(store: Store, tmp_path: Path) -> None:
    store.add_project(make_project(tmp_path))

    with pytest.raises(DuplicateEntityError):
        store.add_project(make_project(tmp_path))


def test_get_missing_project_raises(store: Store) -> None:
    with pytest.raises(ProjectNotFoundError):
        store.get_project("missing")


def test_update_project_persists_status_change(store: Store, tmp_path: Path) -> None:
    project = make_project(tmp_path)
    store.add_project(project)

    project.transition_to(ProjectStatus.PAUSED)
    store.update_project(project)

    assert store.get_project("zenith").status is ProjectStatus.PAUSED


def test_update_missing_project_raises(store: Store, tmp_path: Path) -> None:
    with pytest.raises(ProjectNotFoundError):
        store.update_project(make_project(tmp_path))


def test_list_projects_filters_by_status(store: Store, tmp_path: Path) -> None:
    active = make_project(tmp_path, "active-project")
    paused = make_project(tmp_path, "paused-project")
    paused.transition_to(ProjectStatus.PAUSED)
    store.add_project(active)
    store.add_project(paused)

    assert store.list_projects() == [active, paused]
    assert store.list_projects(status=ProjectStatus.PAUSED) == [paused]


def test_add_and_get_task(store: Store, tmp_path: Path) -> None:
    store.add_project(make_project(tmp_path))
    task = Task(project_id="zenith", title="Write docs")

    store.add_task(task)

    assert store.get_task(task.task_id) == task


def test_add_task_for_missing_project_raises(store: Store) -> None:
    with pytest.raises(StoreError):
        store.add_task(Task(project_id="missing", title="Write docs"))


def test_get_missing_task_raises(store: Store) -> None:
    with pytest.raises(TaskNotFoundError):
        store.get_task(uuid4())


def test_update_task_persists_status_change(store: Store, tmp_path: Path) -> None:
    store.add_project(make_project(tmp_path))
    task = Task(project_id="zenith", title="Write docs")
    store.add_task(task)

    task.transition_to(TaskStatus.READY)
    store.update_task(task)

    assert store.get_task(task.task_id).status is TaskStatus.READY


def test_update_missing_task_raises(store: Store) -> None:
    with pytest.raises(TaskNotFoundError):
        store.update_task(Task(project_id="zenith", title="Write docs"))


def test_list_tasks_filters_by_project_and_status(store: Store, tmp_path: Path) -> None:
    store.add_project(make_project(tmp_path, "first"))
    store.add_project(make_project(tmp_path, "second"))
    ready = Task(project_id="first", title="A", status=TaskStatus.READY)
    draft = Task(project_id="first", title="B")
    other = Task(project_id="second", title="C")
    for task in (ready, draft, other):
        store.add_task(task)

    assert store.list_tasks() == [ready, draft, other]
    assert store.list_tasks(project_id="first") == [ready, draft]
    assert store.list_tasks(project_id="first", status=TaskStatus.READY) == [ready]


def test_add_and_get_session(store: Store, tmp_path: Path) -> None:
    store.add_project(make_project(tmp_path))
    task = Task(project_id="zenith", title="Write docs")
    store.add_task(task)
    session = Session(
        task_id=task.task_id,
        project_id="zenith",
        provider_id="in-memory",
        account_id="personal",
    )

    store.add_session(session)

    assert store.get_session(session.session_id) == session


def test_add_session_for_missing_task_raises(store: Store, tmp_path: Path) -> None:
    store.add_project(make_project(tmp_path))
    session = Session(
        task_id=uuid4(), project_id="zenith", provider_id="in-memory", account_id="a"
    )

    with pytest.raises(StoreError):
        store.add_session(session)


def test_get_missing_session_raises(store: Store) -> None:
    with pytest.raises(SessionNotFoundError):
        store.get_session(uuid4())


def test_update_session_persists_close(store: Store, tmp_path: Path) -> None:
    store.add_project(make_project(tmp_path))
    task = Task(project_id="zenith", title="Write docs")
    store.add_task(task)
    session = Session(
        task_id=task.task_id,
        project_id="zenith",
        provider_id="in-memory",
        account_id="personal",
    )
    store.add_session(session)

    session.transition_to(SessionStatus.COMPLETED)
    session.close(summary="All done")
    store.update_session(session)

    stored = store.get_session(session.session_id)
    assert stored.status is SessionStatus.COMPLETED
    assert stored.summary == "All done"
    assert stored.ended_at is not None


def test_update_missing_session_raises(store: Store) -> None:
    session = Session(
        task_id=uuid4(), project_id="zenith", provider_id="in-memory", account_id="a"
    )

    with pytest.raises(SessionNotFoundError):
        store.update_session(session)


def test_list_sessions_filters_by_task_and_status(store: Store, tmp_path: Path) -> None:
    store.add_project(make_project(tmp_path))
    first_task = Task(project_id="zenith", title="A")
    second_task = Task(project_id="zenith", title="B")
    store.add_task(first_task)
    store.add_task(second_task)

    active = Session(
        task_id=first_task.task_id, project_id="zenith", provider_id="p", account_id="a"
    )
    completed = Session(
        task_id=first_task.task_id,
        project_id="zenith",
        provider_id="p",
        account_id="a",
        status=SessionStatus.COMPLETED,
    )
    other = Session(
        task_id=second_task.task_id, project_id="zenith", provider_id="p", account_id="b"
    )
    for session in (active, completed, other):
        store.add_session(session)

    assert store.list_sessions(task_id=first_task.task_id) == [active, completed]
    assert store.list_sessions(statuses=(SessionStatus.ACTIVE,)) == [active, other]


def test_add_get_and_list_accounts(store: Store) -> None:
    personal = ProviderAccount(provider_id="claude", account_id="personal")
    work = ProviderAccount(provider_id="gemini", account_id="work")
    store.add_account(personal)
    store.add_account(work)

    assert store.get_account("claude", "personal") == personal
    assert store.list_accounts() == [personal, work]
    assert store.list_accounts(provider_id="gemini") == [work]


def test_add_duplicate_account_raises(store: Store) -> None:
    store.add_account(ProviderAccount(provider_id="claude", account_id="personal"))

    with pytest.raises(DuplicateEntityError):
        store.add_account(ProviderAccount(provider_id="claude", account_id="personal"))


def test_same_account_id_on_different_providers_is_allowed(store: Store) -> None:
    store.add_account(ProviderAccount(provider_id="claude", account_id="personal"))
    store.add_account(ProviderAccount(provider_id="gemini", account_id="personal"))

    assert len(store.list_accounts()) == 2


def test_remove_account(store: Store) -> None:
    store.add_account(ProviderAccount(provider_id="claude", account_id="personal"))

    store.remove_account("claude", "personal")

    with pytest.raises(AccountNotFoundError):
        store.get_account("claude", "personal")


def test_remove_missing_account_raises(store: Store) -> None:
    with pytest.raises(AccountNotFoundError):
        store.remove_account("claude", "missing")


def test_event_log_appends_and_lists_newest_first(store: Store) -> None:
    first = ProjectAdded(source="engineering_manager", payload={"project_id": "zenith"})
    second = TaskAdded(source="engineering_manager", payload={"task_id": "t"})
    store.append_event(first)
    store.append_event(second)

    entries = store.list_events()

    assert [entry.name for entry in entries] == ["TaskAdded", "ProjectAdded"]


def test_event_log_respects_limit(store: Store) -> None:
    for index in range(5):
        store.append_event(
            TaskAdded(source="engineering_manager", payload={"index": index})
        )

    assert len(store.list_events(limit=2)) == 2


def test_store_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "em.db"
    store = Store(path)
    store.add_project(make_project(tmp_path))
    store.close()

    reopened = Store(path)
    try:
        assert reopened.get_project("zenith").name == "Zenith"
    finally:
        reopened.close()
