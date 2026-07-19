"""Tests for the Dispatcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_manager.domain.states import (
    ProjectStatus,
    SessionStatus,
    TaskStatus,
)
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import OrchestrationError, ProviderSessionError
from engineering_manager.orchestration.dispatcher import Dispatcher
from engineering_manager.providers.base import (
    Provider,
    SessionHandle,
    SessionSpec,
)
from engineering_manager.providers.in_memory import InMemoryProvider
from engineering_manager.providers.registry import ProviderRegistry
from engineering_manager.store.store import Store


class Harness:
    """A Store + InMemoryProvider + Dispatcher wired together for tests."""

    def __init__(self, tmp_path: Path) -> None:
        self.store = Store(tmp_path / "em.db")
        self.provider = InMemoryProvider()
        self.providers = ProviderRegistry()
        self.providers.register(self.provider)
        self.dispatcher = Dispatcher(self.store, self.providers)

    def add_project(self, project_id: str = "zenith") -> None:
        from engineering_manager.domain.project import Project

        self.store.add_project(
            Project(project_id=project_id, name="Zenith", root_path=Path("."))
        )

    def add_ready_task(
        self,
        title: str = "Write docs",
        priority: int = 0,
        depends_on: frozenset = frozenset(),
        project_id: str = "zenith",
    ) -> Task:
        task = Task(
            project_id=project_id,
            title=title,
            priority=priority,
            depends_on=depends_on,
            status=TaskStatus.READY,
        )
        self.store.add_task(task)
        return task

    def add_account(self, provider_id: str = "in-memory", account_id: str = "a") -> None:
        from engineering_manager.domain.account import ProviderAccount

        self.store.add_account(
            ProviderAccount(provider_id=provider_id, account_id=account_id)
        )

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    harness = Harness(tmp_path)
    yield harness
    harness.close()


def test_eligible_tasks_orders_by_priority_then_age(harness: Harness) -> None:
    harness.add_project()
    low = harness.add_ready_task("low", priority=1)
    high = harness.add_ready_task("high", priority=5)
    other_low = harness.add_ready_task("low-later", priority=1)

    eligible = harness.dispatcher.eligible_tasks()

    assert [task.task_id for task in eligible] == [
        high.task_id,
        low.task_id,
        other_low.task_id,
    ]


def test_eligible_tasks_excludes_unmet_dependencies(harness: Harness) -> None:
    harness.add_project()
    dependency = harness.add_ready_task("dep")
    dependent = harness.add_ready_task("main", depends_on=frozenset({dependency.task_id}))

    assert [t.task_id for t in harness.dispatcher.eligible_tasks()] == [dependency.task_id]

    dependency.transition_to(TaskStatus.IN_PROGRESS)
    dependency.transition_to(TaskStatus.NEEDS_REVIEW)
    dependency.transition_to(TaskStatus.DONE)
    harness.store.update_task(dependency)

    assert [t.task_id for t in harness.dispatcher.eligible_tasks()] == [dependent.task_id]


def test_eligible_tasks_excludes_paused_projects(harness: Harness) -> None:
    harness.add_project()
    harness.add_ready_task()
    project = harness.store.get_project("zenith")
    project.transition_to(ProjectStatus.PAUSED)
    harness.store.update_project(project)

    assert harness.dispatcher.eligible_tasks() == []


def test_dispatch_starts_session_and_marks_task_in_progress(harness: Harness) -> None:
    harness.add_project()
    task = harness.add_ready_task()
    harness.add_account()

    session = harness.dispatcher.dispatch()

    assert session is not None
    assert session.task_id == task.task_id
    assert session.provider_id == "in-memory"
    assert session.external_ref is not None
    assert harness.store.get_task(task.task_id).status is TaskStatus.IN_PROGRESS
    assert harness.store.get_session(session.session_id).status is SessionStatus.ACTIVE


def test_dispatch_passes_project_task_and_instructions_to_provider(
    harness: Harness,
) -> None:
    harness.add_project()
    task = harness.add_ready_task()
    harness.add_account()

    harness.dispatcher.dispatch()

    (spec,) = harness.provider.started_specs
    assert spec.task.task_id == task.task_id
    assert spec.project.project_id == "zenith"
    assert "Write docs" in spec.instructions


def test_dispatch_returns_none_when_no_eligible_task(harness: Harness) -> None:
    harness.add_project()
    harness.add_account()

    assert harness.dispatcher.dispatch() is None


def test_dispatch_without_any_usable_account_raises(harness: Harness) -> None:
    harness.add_project()
    harness.add_ready_task()

    with pytest.raises(OrchestrationError):
        harness.dispatcher.dispatch()


def test_account_on_unregistered_provider_is_not_usable(harness: Harness) -> None:
    harness.add_project()
    harness.add_ready_task()
    harness.add_account(provider_id="unregistered", account_id="x")

    with pytest.raises(OrchestrationError):
        harness.dispatcher.dispatch()


def test_dispatch_returns_none_when_all_accounts_busy(harness: Harness) -> None:
    harness.add_project()
    harness.add_ready_task("first")
    harness.add_ready_task("second")
    harness.add_account()

    first = harness.dispatcher.dispatch()
    second = harness.dispatcher.dispatch()

    assert first is not None
    assert second is None


def test_dispatch_explicit_task_that_is_not_eligible_raises(harness: Harness) -> None:
    harness.add_project()
    harness.add_account()
    task = Task(project_id="zenith", title="Draft only")
    harness.store.add_task(task)

    with pytest.raises(OrchestrationError):
        harness.dispatcher.dispatch(task.task_id)


def test_dispatch_explicit_task_with_no_free_account_raises(harness: Harness) -> None:
    harness.add_project()
    harness.add_ready_task("first")
    second = harness.add_ready_task("second")
    harness.add_account()
    harness.dispatcher.dispatch()

    with pytest.raises(OrchestrationError):
        harness.dispatcher.dispatch(second.task_id)


def test_failed_provider_start_leaves_task_ready(harness: Harness, tmp_path: Path) -> None:
    class ExplodingProvider(Provider):
        @property
        def provider_id(self) -> str:
            return "exploding"

        @property
        def name(self) -> str:
            return "Exploding"

        def start_session(self, spec: SessionSpec) -> SessionHandle:
            raise ProviderSessionError("no capacity")

        def check_session(self, handle: SessionHandle):  # pragma: no cover
            raise ProviderSessionError("unknown")

        def resume_session(self, handle: SessionHandle):  # pragma: no cover
            raise ProviderSessionError("unknown")

        def stop_session(self, handle: SessionHandle) -> None:  # pragma: no cover
            raise ProviderSessionError("unknown")

    harness.providers.register(ExplodingProvider())
    harness.add_project()
    task = harness.add_ready_task()
    harness.add_account(provider_id="exploding", account_id="x")

    with pytest.raises(ProviderSessionError):
        harness.dispatcher.dispatch()

    assert harness.store.get_task(task.task_id).status is TaskStatus.READY
    assert harness.store.list_sessions() == []


def test_complete_session_moves_task_to_needs_review(harness: Harness) -> None:
    harness.add_project()
    task = harness.add_ready_task()
    harness.add_account()
    session = harness.dispatcher.dispatch()

    completed = harness.dispatcher.complete_session(session.session_id, summary="did it")

    assert completed.status is SessionStatus.COMPLETED
    assert completed.summary == "did it"
    assert completed.ended_at is not None
    assert harness.store.get_task(task.task_id).status is TaskStatus.NEEDS_REVIEW


def test_fail_session_moves_task_to_failed(harness: Harness) -> None:
    harness.add_project()
    task = harness.add_ready_task()
    harness.add_account()
    session = harness.dispatcher.dispatch()

    failed = harness.dispatcher.fail_session(session.session_id, reason="crashed")

    assert failed.status is SessionStatus.FAILED
    assert harness.store.get_task(task.task_id).status is TaskStatus.FAILED


def test_interrupt_keeps_task_in_progress(harness: Harness) -> None:
    harness.add_project()
    task = harness.add_ready_task()
    harness.add_account()
    session = harness.dispatcher.dispatch()

    interrupted = harness.dispatcher.interrupt_session(session.session_id)

    assert interrupted.status is SessionStatus.INTERRUPTED
    assert harness.store.get_task(task.task_id).status is TaskStatus.IN_PROGRESS


def test_resume_reactivates_session_with_fresh_ref(harness: Harness) -> None:
    harness.add_project()
    harness.add_ready_task()
    harness.add_account()
    session = harness.dispatcher.dispatch()
    original_ref = session.external_ref
    harness.dispatcher.interrupt_session(session.session_id)

    resumed = harness.dispatcher.resume_session(session.session_id)

    assert resumed.status is SessionStatus.ACTIVE
    assert resumed.external_ref != original_ref
    stored = harness.store.get_session(session.session_id)
    assert stored.external_ref == resumed.external_ref


def test_resume_active_session_raises(harness: Harness) -> None:
    from engineering_manager.exceptions import DomainValidationError

    harness.add_project()
    harness.add_ready_task()
    harness.add_account()
    session = harness.dispatcher.dispatch()

    with pytest.raises(DomainValidationError):
        harness.dispatcher.resume_session(session.session_id)


def test_abandon_returns_task_to_ready_and_frees_account(harness: Harness) -> None:
    harness.add_project()
    task = harness.add_ready_task()
    harness.add_account()
    session = harness.dispatcher.dispatch()

    abandoned = harness.dispatcher.abandon_session(session.session_id, reason="stale")

    assert abandoned.status is SessionStatus.ABANDONED
    assert harness.store.get_task(task.task_id).status is TaskStatus.READY
    # The account is free again, so the same task can be redispatched.
    assert harness.dispatcher.dispatch() is not None


def test_dispatcher_publishes_events_to_log(harness: Harness) -> None:
    harness.add_project()
    harness.add_ready_task()
    harness.add_account()

    session = harness.dispatcher.dispatch()
    harness.dispatcher.complete_session(session.session_id)

    names = [entry.name for entry in harness.store.list_events()]
    assert names == [
        "TaskStatusChanged",  # IN_PROGRESS -> NEEDS_REVIEW
        "SessionStatusChanged",  # ACTIVE -> COMPLETED
        "SessionStarted",
        "TaskStatusChanged",  # READY -> IN_PROGRESS
    ]
