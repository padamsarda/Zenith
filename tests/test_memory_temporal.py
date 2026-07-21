"""Tests for relative time expression resolution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.memory.temporal import TimeWindow, parse_temporal_query, resolve_time_window

# A Wednesday, deliberately mid-week and mid-year so weekday and month
# arithmetic have room to move in both directions.
NOW = datetime(2026, 7, 15, 14, 30, tzinfo=timezone.utc)


def test_no_expression_returns_none() -> None:
    assert resolve_time_window("what is the cubesat battery chemistry", NOW) is None


def test_yesterday_is_the_previous_calendar_day() -> None:
    window = resolve_time_window("what did we decide yesterday", NOW)

    assert window == TimeWindow(
        start=datetime(2026, 7, 14, tzinfo=timezone.utc),
        end=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )


def test_day_before_yesterday() -> None:
    window = resolve_time_window("the day before yesterday", NOW)

    assert window is not None
    assert window.start == datetime(2026, 7, 13, tzinfo=timezone.utc)


def test_today_is_the_current_calendar_day() -> None:
    window = resolve_time_window("what have I done today", NOW)

    assert window == TimeWindow(
        start=datetime(2026, 7, 15, tzinfo=timezone.utc),
        end=datetime(2026, 7, 16, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    ("text", "expected_start"),
    [
        ("3 days ago", datetime(2026, 7, 12, tzinfo=timezone.utc)),
        ("two days ago", datetime(2026, 7, 13, tzinfo=timezone.utc)),
    ],
)
def test_days_ago_is_that_single_day(text: str, expected_start: datetime) -> None:
    window = resolve_time_window(text, NOW)

    assert window is not None
    assert window.start == expected_start
    assert window.end == expected_start + timedelta(days=1)


def test_months_ago_spans_up_to_now() -> None:
    window = resolve_time_window("we talked about this two months ago", NOW)

    assert window is not None
    assert window.end == NOW
    assert window.start == NOW - timedelta(days=60)


def test_last_week_spans_the_previous_seven_days() -> None:
    window = resolve_time_window("what did we work on last week", NOW)

    assert window == TimeWindow(start=NOW - timedelta(days=7), end=NOW)


def test_last_n_months_spans_that_many() -> None:
    window = resolve_time_window("in the last 3 months", NOW)

    assert window is not None
    assert window.start == NOW - timedelta(days=90)


def test_weekday_resolves_to_the_most_recent_one() -> None:
    # NOW is a Wednesday; "monday" means two days back, not next Monday.
    window = resolve_time_window("what did we discuss on monday", NOW)

    assert window is not None
    assert window.start == datetime(2026, 7, 13, tzinfo=timezone.utc)


def test_same_weekday_as_today_resolves_to_a_week_ago() -> None:
    window = resolve_time_window("on wednesday", NOW)

    assert window is not None
    assert window.start == datetime(2026, 7, 8, tzinfo=timezone.utc)


def test_earlier_month_this_year() -> None:
    window = resolve_time_window("that thing in march", NOW)

    assert window == TimeWindow(
        start=datetime(2026, 3, 1, tzinfo=timezone.utc),
        end=datetime(2026, 4, 1, tzinfo=timezone.utc),
    )


def test_later_month_means_last_year() -> None:
    # NOW is July; October has not happened yet this year, so it refers
    # to last year's. Memory only ever looks backward.
    window = resolve_time_window("back in october", NOW)

    assert window is not None
    assert window.start == datetime(2025, 10, 1, tzinfo=timezone.utc)


def test_december_month_window_rolls_the_year() -> None:
    window = resolve_time_window("in december", NOW)

    assert window is not None
    assert window.start == datetime(2025, 12, 1, tzinfo=timezone.utc)
    assert window.end == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_bare_may_does_not_fire_on_the_auxiliary_verb() -> None:
    assert resolve_time_window("you may want to check the battery", NOW) is None


def test_in_may_does_resolve() -> None:
    window = resolve_time_window("we discussed it in may", NOW)

    assert window is not None
    assert window.start == datetime(2026, 5, 1, tzinfo=timezone.utc)


def test_month_name_inside_a_longer_word_does_not_match() -> None:
    assert resolve_time_window("the marching order was clear", NOW) is None


# --- splitting time from subject ----------------------------------------------------------------


def test_parse_strips_the_time_phrase_from_the_subject() -> None:
    # The whole point: "yesterday" becomes a window, and must not remain
    # a word the lexical search hunts for in memory content.
    parsed = parse_temporal_query("what did we decide about the battery yesterday", NOW)

    assert parsed.window is not None
    assert "yesterday" not in parsed.subject.lower()
    assert "battery" in parsed.subject


def test_parse_leaves_text_untouched_with_no_time_expression() -> None:
    parsed = parse_temporal_query("what is the battery chemistry", NOW)

    assert parsed.window is None
    assert parsed.subject == "what is the battery chemistry"


def test_parse_of_a_bare_time_expression_leaves_almost_no_subject() -> None:
    parsed = parse_temporal_query("yesterday", NOW)

    assert parsed.window is not None
    assert parsed.subject == ""


def test_parse_strips_a_multi_word_phrase() -> None:
    parsed = parse_temporal_query("what did we do three days ago about power", NOW)

    assert parsed.window is not None
    assert "days ago" not in parsed.subject.lower()
    assert "power" in parsed.subject


# --- TimeWindow ----------------------------------------------------------------


def test_window_contains_is_half_open() -> None:
    window = TimeWindow(
        start=datetime(2026, 7, 14, tzinfo=timezone.utc),
        end=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )

    assert window.contains(datetime(2026, 7, 14, tzinfo=timezone.utc))
    assert window.contains(datetime(2026, 7, 14, 23, 59, tzinfo=timezone.utc))
    assert not window.contains(datetime(2026, 7, 15, tzinfo=timezone.utc))
