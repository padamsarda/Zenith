"""Tests for the ExecutionEngine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engineering_manager.domain.account import ProviderAccount
from engineering_manager.domain.project import Project
from engineering_manager.domain.states import SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.events import AttentionRequired
from engineering_manager.orchestration.dispatcher import Dispatcher
from engineering_manager.orchestration.engine import (
    DEFAULT_LIMIT_BACKOFF,
    ExecutionEngine,
    TickReport,
)
from engineering_manager.orchestration.retry import LimitedRetryPolicy
from engineering_manager.providers.base import (
    ProviderSessionState,
    ProviderSessionStatus,
    SessionHandle,
)
from engineering_manager.providers.in_memory import InMemoryProvider
from engineering_manager.providers.registry import ProviderRegistry
from engineering_manager.store.store import Store
from shared.events.bus import EventBus
from shared.events.event import Event

START = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)


class Harness:
    """Store + provider + dispatcher + engine with a scripted clock."""

    def __init__(self, tmp_path: Path, max_attempts: int = 3) -> None:
        self.store = Store(tmp_path / "em.db")
        self.provider = InMemoryProvider()
        self.providers = ProviderRegistry()
        self.providers.register(self.provider)
        self.bus = EventBus()
        self.attention: list[Event] = []
        self.bus.subscribe(AttentionRequired, self.attention.append)
        self.now = START
        self.dispatcher = Dispatcher(self.store, self.providers, bus=self.bus)
        self.engine = ExecutionEngine(
            self.store,
            self.dispatcher,
            self.providers,
            retry_policy=LimitedRetryPolicy(max_attempts=max_attempts),
            bus=self.bus,
            clock=lambda: self.now,
        )
        self.store.add_project(
            Project(project_id="zenith", name="Zenith", root_path=Path("."))
        )
        self.store.add_account(
            ProviderAccount(provider_id="in-memory", account_id="a")
        )

    def add_ready_task(self, title: str = "Work", priority: int = 0) -> Task:
        task = Task(
            project_id="zenith", title=title, priority=priority, status=TaskStatus.READY
        )
        self.store.add_task(task)
        return task

    def handle_for(self, session_id) -> SessionHandle:
        session = self.store.get_session(session_id)
        return SessionHandle(
            provider_id=session.provider_id, external_ref=session.external_ref
        )

    def script(self, session_id, state: ProviderSessionState, **kwargs: object) -> None:
        self.provider.script_status(
            self.handle_for(session_id),
            ProviderSessionStatus(state=state, **kwargs),  # type: ignore[arg-type]
        )

    def close(self) -> None:
        self.store.close()


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    harness = Harness(tmp_path)
    yield harness
    harness.close()


def test_tick_on_empty_store_is_idle(harness: Harness) -> None:
    report = harness.engine.tick()

    assert report == TickReport()
    assert report.idle


def test_tick_dispatches_eligible_work(harness: Harness) -> None:
    task = harness.add_ready_task()

    report = harness.engine.tick()

    assert len(report.sessions_started) == 1
    assert harness.store.get_task(task.task_id).status is TaskStatus.IN_PROGRESS
    assert not report.idle


def test_tick_leaves_running_sessions_alone(harness: Harness) -> None:
    harness.add_ready_task()
    (session_id,) = harness.engine.tick().sessions_started

    report = harness.engine.tick()

    assert report.idle
    assert harness.store.get_session(session_id).status is SessionStatus.ACTIVE


def test_tick_completes_finished_sessions(harness: Harness) -> None:
    task = harness.add_ready_task()
    (session_id,) = harness.engine.tick().sessions_started
    harness.script(session_id, ProviderSessionState.FINISHED, detail="All tests green.")

    report = harness.engine.tick()

    assert report.sessions_completed == (session_id,)
    assert harness.store.get_session(session_id).summary == "All tests green."
    assert harness.store.get_task(task.task_id).status is TaskStatus.NEEDS_REVIEW


def test_tick_fails_and_retries_failed_sessions(harness: Harness) -> None:
    task = harness.add_ready_task()
    (session_id,) = harness.engine.tick().sessions_started
    harness.script(session_id, ProviderSessionState.FAILED, detail="Build broke.")

    report = harness.engine.tick()

    assert report.sessions_failed == (session_id,)
    assert report.tasks_retried == (task.task_id,)
    # The retried task is dispatched again within the same tick.
    assert len(report.sessions_started) == 1
    assert harness.store.get_task(task.task_id).status is TaskStatus.IN_PROGRESS


def test_tick_stops_retrying_after_budget_and_flags_attention(tmp_path: Path) -> None:
    harness = Harness(tmp_path, max_attempts=2)
    try:
        task = harness.add_ready_task()
        (session_id,) = harness.engine.tick().sessions_started  # attempt 1
        harness.script(session_id, ProviderSessionState.FAILED)
        report = harness.engine.tick()  # fail, retry, dispatch attempt 2
        (session_id,) = report.sessions_started
        harness.script(session_id, ProviderSessionState.FAILED)
        report = harness.engine.tick()  # second failure exhausts the budget

        assert report.tasks_exhausted == (task.task_id,)
        assert report.sessions_started == ()
        assert harness.store.get_task(task.task_id).status is TaskStatus.FAILED
        kinds = [event.payload["kind"] for event in harness.attention]
        assert kinds == ["task_retries_exhausted"]
    finally:
        harness.close()


def test_exhausted_task_does_not_republish_attention(tmp_path: Path) -> None:
    harness = Harness(tmp_path, max_attempts=1)
    try:
        harness.add_ready_task()
        (session_id,) = harness.engine.tick().sessions_started
        harness.script(session_id, ProviderSessionState.FAILED)
        harness.engine.tick()
        assert len(harness.attention) == 1

        report = harness.engine.tick()

        assert len(harness.attention) == 1
        assert len(report.tasks_exhausted) == 1
    finally:
        harness.close()


def test_tick_interrupts_limit_reached_with_reported_resume_time(
    harness: Harness,
) -> None:
    harness.add_ready_task()
    (session_id,) = harness.engine.tick().sessions_started
    resume_at = START + timedelta(hours=5)
    harness.script(session_id, ProviderSessionState.LIMIT_REACHED, resume_at=resume_at)

    report = harness.engine.tick()

    session = harness.store.get_session(session_id)
    assert report.sessions_interrupted == (session_id,)
    assert session.status is SessionStatus.INTERRUPTED
    assert session.resume_at == resume_at


def test_tick_backs_off_when_limit_has_no_resume_time(harness: Harness) -> None:
    harness.add_ready_task()
    (session_id,) = harness.engine.tick().sessions_started
    harness.script(session_id, ProviderSessionState.LIMIT_REACHED)

    harness.engine.tick()

    assert harness.store.get_session(session_id).resume_at == START + DEFAULT_LIMIT_BACKOFF


def test_tick_resumes_interrupted_session_once_due(harness: Harness) -> None:
    task = harness.add_ready_task()
    (session_id,) = harness.engine.tick().sessions_started
    harness.script(session_id, ProviderSessionState.LIMIT_REACHED)
    harness.engine.tick()

    assert harness.engine.tick().sessions_resumed == ()  # not yet due

    harness.now = START + DEFAULT_LIMIT_BACKOFF
    report = harness.engine.tick()

    session = harness.store.get_session(session_id)
    assert report.sessions_resumed == (session_id,)
    assert session.status is SessionStatus.ACTIVE
    assert session.resume_at is None
    assert harness.store.get_task(task.task_id).status is TaskStatus.IN_PROGRESS


def test_tick_never_auto_resumes_awaiting_input(harness: Harness) -> None:
    harness.add_ready_task()
    (session_id,) = harness.engine.tick().sessions_started
    harness.script(session_id, ProviderSessionState.AWAITING_INPUT, detail="Which DB?")

    report = harness.engine.tick()

    assert report.sessions_interrupted == (session_id,)
    assert harness.store.get_session(session_id).resume_at is None
    assert [event.payload["kind"] for event in harness.attention] == [
        "session_awaiting_input"
    ]

    harness.now = START + timedelta(days=365)
    assert harness.engine.tick().sessions_resumed == ()


def test_tick_fails_sessions_the_provider_lost(harness: Harness) -> None:
    """Crash recovery: a session the provider no longer knows is failed
    and its task re-queued by the retry policy."""
    task = harness.add_ready_task()
    (session_id,) = harness.engine.tick().sessions_started
    session = harness.store.get_session(session_id)
    session.update_external_ref("in-memory/vanished")
    harness.store.update_session(session)

    report = harness.engine.tick()

    assert report.sessions_failed == (session_id,)
    assert report.tasks_retried == (task.task_id,)
    stored = harness.store.get_session(session_id)
    assert stored.status is SessionStatus.FAILED
    assert stored.summary is not None and "lost" in stored.summary


def test_tick_dispatches_until_accounts_saturate(harness: Harness) -> None:
    harness.store.add_account(ProviderAccount(provider_id="in-memory", account_id="b"))
    harness.add_ready_task("first", priority=2)
    harness.add_ready_task("second", priority=1)
    harness.add_ready_task("third", priority=0)

    report = harness.engine.tick()

    assert len(report.sessions_started) == 2  # two accounts, three tasks
    ready = harness.store.list_tasks(status=TaskStatus.READY)
    assert [task.title for task in ready] == ["third"]


def test_tick_reports_missing_configuration_as_attention(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    try:
        harness.store.remove_account("in-memory", "a")
        harness.add_ready_task()

        report = harness.engine.tick()

        assert report.sessions_started == ()
        assert any("account" in notice for notice in report.attention)
    finally:
        harness.close()


def test_full_lifecycle_across_interruption_completes_task(harness: Harness) -> None:
    """A task survives dispatch -> limit -> resume -> finish across ticks."""
    task = harness.add_ready_task()
    (session_id,) = harness.engine.tick().sessions_started
    harness.script(session_id, ProviderSessionState.LIMIT_REACHED)
    harness.engine.tick()
    harness.now = START + DEFAULT_LIMIT_BACKOFF
    harness.engine.tick()
    # Resuming issued a fresh external_ref; finish the resumed session.
    harness.script(session_id, ProviderSessionState.FINISHED, detail="Done after resume.")

    report = harness.engine.tick()

    assert report.sessions_completed == (session_id,)
    assert harness.store.get_task(task.task_id).status is TaskStatus.NEEDS_REVIEW
    assert harness.store.get_session(session_id).summary == "Done after resume."


def test_run_ticks_until_max_and_sleeps_between(harness: Harness) -> None:
    naps: list[float] = []
    harness.add_ready_task()

    harness.engine.run(interval_seconds=5.0, max_ticks=3, sleep=naps.append)

    assert naps == [5.0, 5.0]
    assert len(harness.store.list_sessions()) == 1


def test_run_stops_cleanly_on_keyboard_interrupt(harness: Harness) -> None:
    def interrupt(_: float) -> None:
        raise KeyboardInterrupt

    harness.add_ready_task()

    harness.engine.run(interval_seconds=1.0, max_ticks=10, sleep=interrupt)

    assert len(harness.store.list_sessions()) == 1
