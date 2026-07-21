"""Tests for VerificationPolicy and its implementations."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from engineering_manager.domain.project import Project
from engineering_manager.domain.task import Task
from engineering_manager.exceptions import OrchestrationError
from engineering_manager.orchestration.verification import (
    CommandVerificationPolicy,
    NoVerificationPolicy,
    VerificationResult,
)


def _project(root_path: Path) -> Project:
    return Project(project_id="zenith", name="Zenith", root_path=root_path)


def _task() -> Task:
    return Task(project_id="zenith", title="Do the work")


def test_no_verification_policy_always_passes(tmp_path: Path) -> None:
    result = NoVerificationPolicy().verify(_task(), _project(tmp_path))

    assert result == VerificationResult(passed=True)


def test_command_verification_policy_passes_on_zero_exit(tmp_path: Path) -> None:
    policy = CommandVerificationPolicy((sys.executable, "-c", "print('all good')"))

    result = policy.verify(_task(), _project(tmp_path))

    assert result.passed
    assert result.detail is not None and "all good" in result.detail


def test_command_verification_policy_fails_on_nonzero_exit(tmp_path: Path) -> None:
    policy = CommandVerificationPolicy(
        (sys.executable, "-c", "import sys; print('boom'); sys.exit(1)")
    )

    result = policy.verify(_task(), _project(tmp_path))

    assert not result.passed
    assert result.detail is not None
    assert "exit 1" in result.detail
    assert "boom" in result.detail


def test_command_verification_policy_fails_when_project_missing(tmp_path: Path) -> None:
    policy = CommandVerificationPolicy((sys.executable, "-c", "print('unreached')"))

    result = policy.verify(_task(), _project(tmp_path / "does-not-exist"))

    assert not result.passed
    assert result.detail is not None and "does not exist" in result.detail


def test_command_verification_policy_reports_timeout(tmp_path: Path) -> None:
    policy = CommandVerificationPolicy(
        (sys.executable, "-c", "import time; time.sleep(5)"), timeout_seconds=0.1
    )

    result = policy.verify(_task(), _project(tmp_path))

    assert not result.passed
    assert result.detail is not None and "timed out" in result.detail


def test_command_verification_policy_truncates_long_output(tmp_path: Path) -> None:
    policy = CommandVerificationPolicy(
        (sys.executable, "-c", "print('x' * 1000)"), detail_tail_chars=20
    )

    result = policy.verify(_task(), _project(tmp_path))

    assert result.passed
    assert result.detail is not None and len(result.detail) == 20


@pytest.mark.parametrize(
    "kwargs",
    [
        {"command": ()},
        {"timeout_seconds": 0},
        {"timeout_seconds": -1},
        {"detail_tail_chars": -1},
    ],
)
def test_command_verification_policy_rejects_bad_construction(kwargs: dict[str, object]) -> None:
    defaults: dict[str, object] = {
        "command": (sys.executable, "-c", "pass"),
        "timeout_seconds": 5.0,
        "detail_tail_chars": 100,
    }
    defaults.update(kwargs)

    with pytest.raises(OrchestrationError):
        CommandVerificationPolicy(
            defaults["command"],  # type: ignore[arg-type]
            timeout_seconds=defaults["timeout_seconds"],  # type: ignore[arg-type]
            detail_tail_chars=defaults["detail_tail_chars"],  # type: ignore[arg-type]
        )
