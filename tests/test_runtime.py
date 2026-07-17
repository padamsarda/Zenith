"""Tests for the Runtime lifecycle owner."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.exceptions import ZenithRuntimeError
from runtime.runtime import Runtime
from runtime.state import RuntimeState

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_runtime_creation_starts_initializing() -> None:
    runtime = Runtime(base_path=PROJECT_ROOT)

    assert runtime.state is RuntimeState.INITIALIZING


def test_runtime_start_transitions_to_running() -> None:
    runtime = Runtime(base_path=PROJECT_ROOT)

    runtime.start()

    assert runtime.state is RuntimeState.RUNNING
    runtime.stop()


def test_runtime_stop_transitions_to_stopped() -> None:
    runtime = Runtime(base_path=PROJECT_ROOT)
    runtime.start()

    runtime.stop()

    assert runtime.state is RuntimeState.STOPPED


def test_runtime_stop_is_idempotent() -> None:
    runtime = Runtime(base_path=PROJECT_ROOT)
    runtime.start()
    runtime.stop()

    runtime.stop()

    assert runtime.state is RuntimeState.STOPPED


def test_runtime_start_fails_with_missing_folders(tmp_path: Path) -> None:
    runtime = Runtime(base_path=tmp_path)

    with pytest.raises(ZenithRuntimeError):
        runtime.start()

    assert runtime.state is RuntimeState.FAILED
