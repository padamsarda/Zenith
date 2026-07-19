"""Tests for the Runtime lifecycle owner."""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.events.event import Event
from runtime.events.lifecycle_events import (
    ApplicationStarted,
    ApplicationStarting,
    ApplicationStartupFailed,
    ApplicationStopped,
    ApplicationStopping,
    ConfigurationLoaded,
)
from runtime.runtime import Runtime
from runtime.state import RuntimeState
from shared.exceptions import ZenithRuntimeError

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


def test_runtime_has_an_application_context() -> None:
    runtime = Runtime(base_path=PROJECT_ROOT)

    assert runtime.context.state is RuntimeState.INITIALIZING


def test_runtime_start_emits_application_starting() -> None:
    runtime = Runtime(base_path=PROJECT_ROOT)
    received: list[Event] = []
    runtime.context.events.subscribe(ApplicationStarting, received.append)

    runtime.start()

    assert len(received) == 1
    runtime.stop()


def test_runtime_start_emits_application_started() -> None:
    runtime = Runtime(base_path=PROJECT_ROOT)
    received: list[Event] = []
    runtime.context.events.subscribe(ApplicationStarted, received.append)

    runtime.start()

    assert len(received) == 1
    runtime.stop()


def test_runtime_start_emits_configuration_loaded() -> None:
    runtime = Runtime(base_path=PROJECT_ROOT)
    received: list[Event] = []
    runtime.context.events.subscribe(ConfigurationLoaded, received.append)

    runtime.start()

    assert len(received) == 1
    runtime.stop()


def test_runtime_stop_emits_application_stopping_and_stopped() -> None:
    runtime = Runtime(base_path=PROJECT_ROOT)
    stopping: list[Event] = []
    stopped: list[Event] = []
    runtime.context.events.subscribe(ApplicationStopping, stopping.append)
    runtime.context.events.subscribe(ApplicationStopped, stopped.append)
    runtime.start()

    runtime.stop()

    assert len(stopping) == 1
    assert len(stopped) == 1


def test_runtime_start_failure_emits_application_startup_failed(tmp_path: Path) -> None:
    runtime = Runtime(base_path=tmp_path)
    received: list[Event] = []
    runtime.context.events.subscribe(ApplicationStartupFailed, received.append)

    with pytest.raises(ZenithRuntimeError):
        runtime.start()

    assert len(received) == 1
    assert "reason" in received[0].payload


def test_runtime_events_are_emitted_in_lifecycle_order() -> None:
    runtime = Runtime(base_path=PROJECT_ROOT)
    order: list[str] = []
    runtime.context.events.subscribe(ApplicationStarting, lambda e: order.append(e.name))
    runtime.context.events.subscribe(ApplicationStarted, lambda e: order.append(e.name))
    runtime.context.events.subscribe(ApplicationStopping, lambda e: order.append(e.name))
    runtime.context.events.subscribe(ApplicationStopped, lambda e: order.append(e.name))

    runtime.start()
    runtime.stop()

    assert order == [
        "ApplicationStarting",
        "ApplicationStarted",
        "ApplicationStopping",
        "ApplicationStopped",
    ]


def test_runtime_events_carry_runtime_as_source() -> None:
    runtime = Runtime(base_path=PROJECT_ROOT)
    received: list[Event] = []
    runtime.context.events.subscribe(ApplicationStarting, received.append)

    runtime.start()

    assert received[0].source == "runtime"
    runtime.stop()


def test_runtime_stop_after_failed_start_stays_failed(tmp_path: Path) -> None:
    runtime = Runtime(base_path=tmp_path)
    with pytest.raises(ZenithRuntimeError):
        runtime.start()

    runtime.stop()

    assert runtime.state is RuntimeState.FAILED


def test_runtime_stop_after_failed_start_emits_no_stop_events(tmp_path: Path) -> None:
    runtime = Runtime(base_path=tmp_path)
    stopping: list[Event] = []
    stopped: list[Event] = []
    runtime.context.events.subscribe(ApplicationStopping, stopping.append)
    runtime.context.events.subscribe(ApplicationStopped, stopped.append)
    with pytest.raises(ZenithRuntimeError):
        runtime.start()

    runtime.stop()

    assert stopping == []
    assert stopped == []


def test_runtime_start_survives_failing_listener() -> None:
    runtime = Runtime(base_path=PROJECT_ROOT)

    def failing_listener(event: Event) -> None:
        raise ValueError("boom")

    runtime.context.events.subscribe(ApplicationStarting, failing_listener)

    runtime.start()

    assert runtime.state is RuntimeState.RUNNING
    runtime.stop()
