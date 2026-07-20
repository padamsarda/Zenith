"""Tests for the RetryPolicy seam."""

from __future__ import annotations

from uuid import uuid4

import pytest

from engineering_manager.domain.session import Session
from engineering_manager.domain.states import SessionStatus, TaskStatus
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import OrchestrationError
from engineering_manager.orchestration.retry import (
    DEFAULT_MAX_ATTEMPTS,
    LimitedRetryPolicy,
    RetryPolicy,
)


def make_failed_session(task: Task) -> Session:
    return Session(
        task_id=task.task_id,
        project_id=task.project_id,
        provider_id="in-memory",
        account_id="a",
        status=SessionStatus.FAILED,
    )


def make_failed_task() -> Task:
    return Task(project_id="zenith", title="Broken", status=TaskStatus.FAILED)


def test_limited_retry_policy_is_a_retry_policy() -> None:
    assert isinstance(LimitedRetryPolicy(), RetryPolicy)


def test_retries_while_attempts_remain() -> None:
    policy = LimitedRetryPolicy(max_attempts=2)
    task = make_failed_task()

    assert policy.should_retry(task, [make_failed_session(task)])


def test_stops_once_max_attempts_have_failed() -> None:
    policy = LimitedRetryPolicy(max_attempts=2)
    task = make_failed_task()
    failures = [make_failed_session(task), make_failed_session(task)]

    assert not policy.should_retry(task, failures)


def test_default_budget_is_three_attempts() -> None:
    policy = LimitedRetryPolicy()
    task = make_failed_task()
    failures = [make_failed_session(task) for _ in range(DEFAULT_MAX_ATTEMPTS)]

    assert policy.max_attempts == DEFAULT_MAX_ATTEMPTS
    assert policy.should_retry(task, failures[:-1])
    assert not policy.should_retry(task, failures)


def test_max_attempts_must_be_positive() -> None:
    with pytest.raises(OrchestrationError):
        LimitedRetryPolicy(max_attempts=0)


def test_max_attempts_rejects_non_int() -> None:
    with pytest.raises(OrchestrationError):
        LimitedRetryPolicy(max_attempts="3")  # type: ignore[arg-type]
    with pytest.raises(OrchestrationError):
        LimitedRetryPolicy(max_attempts=True)


def test_unused_task_id_does_not_matter() -> None:
    policy = LimitedRetryPolicy(max_attempts=1)
    task = make_failed_task()
    other = Task(project_id="zenith", title="Other", task_id=uuid4())

    assert policy.should_retry(other, [])
    assert not policy.should_retry(task, [make_failed_session(task)])
