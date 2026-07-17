"""Tests for the PluginState enum."""

from __future__ import annotations

from runtime.plugins.state import TERMINAL_STATES, PluginState


def test_expected_states_exist() -> None:
    expected_names = {
        "CREATED",
        "INITIALIZED",
        "REGISTERED",
        "ENABLED",
        "DISABLED",
        "STOPPED",
        "FAILED",
    }

    assert {state.name for state in PluginState} == expected_names


def test_states_have_distinct_values() -> None:
    values = [state.value for state in PluginState]

    assert len(values) == len(set(values))


def test_terminal_states_contains_stopped() -> None:
    assert PluginState.STOPPED in TERMINAL_STATES


def test_terminal_states_contains_failed() -> None:
    assert PluginState.FAILED in TERMINAL_STATES


def test_terminal_states_excludes_created() -> None:
    assert PluginState.CREATED not in TERMINAL_STATES


def test_terminal_states_excludes_initialized() -> None:
    assert PluginState.INITIALIZED not in TERMINAL_STATES


def test_terminal_states_excludes_registered() -> None:
    assert PluginState.REGISTERED not in TERMINAL_STATES


def test_terminal_states_excludes_enabled() -> None:
    assert PluginState.ENABLED not in TERMINAL_STATES


def test_terminal_states_excludes_disabled() -> None:
    assert PluginState.DISABLED not in TERMINAL_STATES


def test_terminal_states_has_exactly_two_members() -> None:
    assert len(TERMINAL_STATES) == 2
