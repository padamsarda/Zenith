"""Tests for ExponentialBackoffRetryPolicy."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from engineering_manager.domain.session import Session
from engineering_manager.domain.states import SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import OrchestrationError
from engineering_manager.orchestration.retry import ExponentialBackoffRetryPolicy, RetryPolicy

START = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)


def make_failed_task() -> Task:
    return Task(project_id="zenith", title="Broken", status=TaskStatus.FAILED)


def make_failed_session(task: Task, ended_at: datetime) -> Session:
    return Session(
        task_id=task.task_id,
        project_id=task.project_id,
        provider_id="in-memory",
        account_id="a",
        status=SessionStatus.FAILED,
        started_at=ended_at - timedelta(seconds=1),
        ended_at=ended_at,
    )


def test_is_a_retry_policy() -> None:
    assert isinstance(ExponentialBackoffRetryPolicy(), RetryPolicy)


def test_retries_immediately_with_no_prior_failures() -> None:
    policy = ExponentialBackoffRetryPolicy(clock=lambda: START)

    assert policy.should_retry(make_failed_task(), [])


def test_denies_retry_before_base_delay_has_elapsed() -> None:
    task = make_failed_task()
    policy = ExponentialBackoffRetryPolicy(
        base_delay=timedelta(minutes=1), clock=lambda: START + timedelta(seconds=30)
    )
    failed = [make_failed_session(task, START)]

    assert not policy.should_retry(task, failed)


def test_allows_retry_once_base_delay_has_elapsed() -> None:
    task = make_failed_task()
    policy = ExponentialBackoffRetryPolicy(
        base_delay=timedelta(minutes=1), clock=lambda: START + timedelta(minutes=1)
    )
    failed = [make_failed_session(task, START)]

    assert policy.should_retry(task, failed)


def test_delay_doubles_after_the_second_failure() -> None:
    task = make_failed_task()
    second_failure = START + timedelta(minutes=10)
    failed = [make_failed_session(task, START), make_failed_session(task, second_failure)]

    # Only base_delay (1 min) since the second failure: not enough for
    # the doubled (2 min) delay a second attempt requires.
    not_yet = ExponentialBackoffRetryPolicy(
        max_attempts=5,
        base_delay=timedelta(minutes=1),
        clock=lambda: second_failure + timedelta(minutes=1),
    )
    assert not not_yet.should_retry(task, failed)

    ready = ExponentialBackoffRetryPolicy(
        max_attempts=5,
        base_delay=timedelta(minutes=1),
        clock=lambda: second_failure + timedelta(minutes=2),
    )
    assert ready.should_retry(task, failed)


def test_measures_delay_from_the_most_recent_failure() -> None:
    task = make_failed_task()
    first_failure = START
    second_failure = START + timedelta(hours=1)
    failed = [make_failed_session(task, second_failure), make_failed_session(task, first_failure)]
    policy = ExponentialBackoffRetryPolicy(
        max_attempts=5,
        base_delay=timedelta(minutes=1),
        clock=lambda: first_failure + timedelta(minutes=5),
    )

    # Base delay has long passed since first_failure, but the most
    # recent failure was second_failure, one hour later.
    assert not policy.should_retry(task, failed)


def test_stops_once_max_attempts_have_failed_regardless_of_elapsed_time() -> None:
    task = make_failed_task()
    policy = ExponentialBackoffRetryPolicy(
        max_attempts=2, base_delay=timedelta(seconds=0), clock=lambda: START + timedelta(days=1)
    )
    failed = [make_failed_session(task, START), make_failed_session(task, START)]

    assert not policy.should_retry(task, failed)


def test_default_budget_is_three_attempts() -> None:
    policy = ExponentialBackoffRetryPolicy(base_delay=timedelta(0), clock=lambda: START)

    assert policy.max_attempts == 3


def test_max_attempts_must_be_positive() -> None:
    with pytest.raises(OrchestrationError):
        ExponentialBackoffRetryPolicy(max_attempts=0)


def test_base_delay_must_be_non_negative() -> None:
    with pytest.raises(OrchestrationError):
        ExponentialBackoffRetryPolicy(base_delay=timedelta(seconds=-1))


def test_base_delay_must_be_a_timedelta() -> None:
    with pytest.raises(OrchestrationError):
        ExponentialBackoffRetryPolicy(base_delay=60)  # type: ignore[arg-type]


def test_multiplier_must_be_at_least_one() -> None:
    with pytest.raises(OrchestrationError):
        ExponentialBackoffRetryPolicy(multiplier=0.5)


def test_falls_back_to_started_at_when_a_session_never_closed() -> None:
    task = make_failed_task()
    # A session marked FAILED directly (as tests elsewhere do) without
    # going through close() has no ended_at.
    session = Session(
        task_id=task.task_id,
        project_id=task.project_id,
        provider_id="in-memory",
        account_id="a",
        status=SessionStatus.FAILED,
        started_at=START,
    )
    policy = ExponentialBackoffRetryPolicy(
        base_delay=timedelta(minutes=1), clock=lambda: START + timedelta(seconds=30)
    )

    assert not policy.should_retry(task, [session])


def test_unused_task_id_does_not_matter() -> None:
    policy = ExponentialBackoffRetryPolicy(max_attempts=1, clock=lambda: START)
    task = make_failed_task()
    other = Task(project_id="zenith", title="Other", task_id=uuid4())

    assert policy.should_retry(other, [])
    assert not policy.should_retry(task, [make_failed_session(task, START)])
