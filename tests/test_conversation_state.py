"""Tests for the ConversationState enum."""

from __future__ import annotations

from runtime.conversation.state import TERMINAL_STATES, ConversationState


def test_expected_states_exist() -> None:
    expected_names = {"ACTIVE", "ARCHIVED"}

    assert {state.name for state in ConversationState} == expected_names


def test_states_have_distinct_values() -> None:
    values = [state.value for state in ConversationState]

    assert len(values) == len(set(values))


def test_terminal_states_contains_archived() -> None:
    assert ConversationState.ARCHIVED in TERMINAL_STATES


def test_terminal_states_excludes_active() -> None:
    assert ConversationState.ACTIVE not in TERMINAL_STATES


def test_terminal_states_has_exactly_one_member() -> None:
    assert len(TERMINAL_STATES) == 1
