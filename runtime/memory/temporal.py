"""Resolving relative time expressions in a query into absolute windows.

"What did we decide yesterday" is only answerable if "yesterday" becomes
a concrete pair of timestamps *at the moment the question is asked* —
the same expression means a different day every day, so a memory system
that stores or matches the phrase itself gets steadily more wrong. This
module turns the expression into a `TimeWindow` against a supplied
`now`, which the retrieval policy then uses to narrow candidates before
scoring them (ADR 0027).

Deliberately a small, explicit vocabulary rather than a general date
parser: every pattern here is one a person actually says to an
assistant, and an unrecognized phrase yields `None` — "no time
constraint", which degrades to ordinary relevance ranking rather than
guessing at a window and silently hiding the right answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

MONTHS: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

WEEKDAYS: dict[str, int] = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

_NUMBER_WORDS: dict[str, int] = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_UNIT_DAYS: dict[str, int] = {
    "day": 1,
    "week": 7,
    "month": 30,
    "year": 365,
}

_AGO_PATTERN = re.compile(
    r"\b(?P<count>\d+|" + "|".join(_NUMBER_WORDS) + r")\s+"
    r"(?P<unit>day|week|month|year)s?\s+ago\b"
)
_LAST_N_PATTERN = re.compile(
    r"\b(?:last|past|previous)\s+(?P<count>\d+|" + "|".join(_NUMBER_WORDS) + r")?\s*"
    r"(?P<unit>day|week|month|year)s?\b"
)


@dataclass(frozen=True)
class TimeWindow:
    """An absolute, half-open interval `[start, end)` a memory may fall in."""

    start: datetime
    end: datetime

    def contains(self, moment: datetime) -> bool:
        """Return whether `moment` falls within this window."""
        return self.start <= moment < self.end


@dataclass(frozen=True)
class TemporalQuery:
    """A query split into its time constraint and its remaining subject.

    Splitting matters: once "yesterday" has become a `window`, leaving it
    in the text makes the lexical search hunt for memories containing the
    *word* "yesterday" — which is not what was asked and generally
    matches nothing. `subject` is the query with the recognized time
    expression removed, and is what should actually be searched for.
    """

    window: TimeWindow | None
    subject: str


def _day_bounds(moment: datetime) -> TimeWindow:
    """The calendar day containing `moment`, midnight to midnight."""
    start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return TimeWindow(start=start, end=start + timedelta(days=1))


def _count_from(token: str | None) -> int:
    """Turn a digit or number word into an int, defaulting to 1."""
    if not token:
        return 1
    return int(token) if token.isdigit() else _NUMBER_WORDS.get(token, 1)


def _month_window(now: datetime, month: int) -> TimeWindow:
    """The most recent occurrence of calendar month `month`, at or before `now`.

    A month later in the calendar than `now`'s own month refers to last
    year — in July, "in October" means the October that already happened,
    not the one still three months away. Memory only ever looks backward.
    """
    year = now.year if month <= now.month else now.year - 1
    start = datetime(year, month, 1, tzinfo=now.tzinfo)
    end = (
        datetime(year + 1, 1, 1, tzinfo=now.tzinfo)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=now.tzinfo)
    )
    return TimeWindow(start=start, end=end)


def _weekday_window(now: datetime, weekday: int) -> TimeWindow:
    """The most recent occurrence of `weekday` strictly before today."""
    days_back = (now.weekday() - weekday) % 7 or 7
    return _day_bounds(now - timedelta(days=days_back))


def _match(text: str, now: datetime) -> tuple[TimeWindow, str] | None:
    """Find the first time expression in `text`, returning its window and the phrase.

    The phrase is returned so callers can strip it from the query; every
    branch reports the exact substring it matched on.
    """
    lowered = text.lower()

    # Checked before the bare "yesterday" it contains, or that broader
    # match would swallow it and answer with the wrong day.
    if "day before yesterday" in lowered:
        return _day_bounds(now - timedelta(days=2)), "day before yesterday"
    if "yesterday" in lowered:
        return _day_bounds(now - timedelta(days=1)), "yesterday"
    for phrase in ("this morning", "earlier today", "today"):
        if phrase in lowered:
            return _day_bounds(now), phrase

    match = _AGO_PATTERN.search(lowered)
    if match:
        days = _count_from(match.group("count")) * _UNIT_DAYS[match.group("unit")]
        moment = now - timedelta(days=days)
        # A day-granular "ago" means that day; coarser units mean
        # everything since, since nobody means a single day when they say
        # "two months ago" — they mean around then, and a window that
        # narrow would usually miss.
        window = (
            _day_bounds(moment)
            if match.group("unit") == "day"
            else TimeWindow(start=moment, end=now)
        )
        return window, match.group(0)

    match = _LAST_N_PATTERN.search(lowered)
    if match:
        days = _count_from(match.group("count")) * _UNIT_DAYS[match.group("unit")]
        return TimeWindow(start=now - timedelta(days=days), end=now), match.group(0)

    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", lowered):
            return _weekday_window(now, weekday), name

    for name, month in MONTHS.items():
        # Guarded by word boundaries so "march" doesn't fire on "marching"
        # and "may" doesn't fire on the far more common auxiliary verb.
        if re.search(rf"\b{name}\b", lowered) and (name != "may" or "in may" in lowered):
            return _month_window(now, month), name

    return None


def resolve_time_window(text: str, now: datetime) -> TimeWindow | None:
    """Resolve the first relative time expression in `text` against `now`.

    Returns `None` when `text` carries no recognized time expression,
    which callers must read as "no time constraint" rather than "no
    matches" — an unrecognized phrase must never narrow a search to
    nothing.
    """
    found = _match(text, now)
    return found[0] if found else None


def parse_temporal_query(text: str, now: datetime) -> TemporalQuery:
    """Split `text` into its time constraint and the subject to search for.

    The subject is `text` with the recognized time phrase removed, so a
    lexical search never hunts for the word "yesterday" in memory
    content. With no time expression present, the subject is `text`
    unchanged.
    """
    found = _match(text, now)
    if found is None:
        return TemporalQuery(window=None, subject=text)

    window, phrase = found
    subject = re.sub(re.escape(phrase), " ", text, flags=re.IGNORECASE)
    return TemporalQuery(window=window, subject=subject.strip())
