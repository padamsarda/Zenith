"""Tests for the salience rules deciding what is worth remembering."""

from __future__ import annotations

import pytest

from runtime.memory.memory import MAX_IMPORTANCE, MemoryKind
from runtime.memory.salience import classify, has_explicit_marker, is_trivial, score_importance


# --- what is skipped ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "open spotify",
        "launch vs code",
        "close chrome",
        "play comfortably numb",
        "pause the music",
        "skip this track",
        "turn up the volume",
        "volume down",
        "mute",
        "switch to notion",
        "thanks",
        "ok",
        "hello",
        "what's the time",
    ],
)
def test_device_commands_and_pleasantries_are_trivial(text: str) -> None:
    assert is_trivial(text) is True


def test_very_short_text_is_trivial() -> None:
    assert is_trivial("yep") is True


# --- what is kept ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "The CubeSat battery is an 18650 lithium cell pack",
        "We decided to use an MPPT charge controller",
        "I prefer dark mode in every editor",
        "I need to finish the power budget spreadsheet",
        "remember that my student ID is f20250775",
    ],
)
def test_substantive_statements_are_kept(text: str) -> None:
    assert is_trivial(text) is False


def test_explicit_marker_overrides_a_trivial_shape() -> None:
    # A command-shaped sentence the user explicitly asked to remember is
    # a preference about behavior, not a one-off command.
    assert is_trivial("remember that I always open Spotify after VS Code") is False


# --- explicit markers ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "remember that the battery is lithium",
        "remember this: the deadline is Friday",
        "don't forget the antenna deploys after 30 minutes",
        "keep in mind that I work in IST",
        "from now on use metric units",
    ],
)
def test_explicit_markers_are_detected(text: str) -> None:
    assert has_explicit_marker(text) is True


def test_ordinary_statement_has_no_explicit_marker() -> None:
    assert has_explicit_marker("the battery is lithium") is False


# --- classification ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I prefer dark mode", MemoryKind.PREFERENCE),
        ("I always use metric units", MemoryKind.PREFERENCE),
        ("we decided to use MPPT", MemoryKind.DECISION),
        ("we agreed on 18650 cells", MemoryKind.DECISION),
        ("I need to finish the power budget", MemoryKind.TASK),
        ("remind me to order the antenna", MemoryKind.TASK),
        ("the solar panel is 6 watts", MemoryKind.FACT),
    ],
)
def test_classification(text: str, expected: MemoryKind) -> None:
    assert classify(text) is expected


# --- importance ----------------------------------------------------------------


def test_explicit_request_scores_maximum_importance() -> None:
    text = "remember that the deadline is Friday"

    assert score_importance(text, classify(text)) == MAX_IMPORTANCE


def test_decision_outranks_a_bare_fact() -> None:
    decision = score_importance("we decided on MPPT", MemoryKind.DECISION)
    fact = score_importance("the panel is 6 watts", MemoryKind.FACT)

    assert decision > fact


def test_preference_outranks_a_bare_fact() -> None:
    preference = score_importance("I prefer dark mode", MemoryKind.PREFERENCE)
    fact = score_importance("the panel is 6 watts", MemoryKind.FACT)

    assert preference > fact
