"""Tests for the RuntimeState enum."""

from __future__ import annotations

from runtime.state import RuntimeState


def test_expected_states_exist() -> None:
    expected_names = {
        "INITIALIZING",
        "STARTING",
        "RUNNING",
        "STOPPING",
        "STOPPED",
        "FAILED",
    }

    assert {state.name for state in RuntimeState} == expected_names


def test_states_have_distinct_values() -> None:
    values = [state.value for state in RuntimeState]

    assert len(values) == len(set(values))
