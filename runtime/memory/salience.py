"""Deciding what is worth remembering, and how much.

A memory system that stores everything is barely better than one that
stores nothing: the signal drowns. "Open Spotify" is re-derivable in a
second and never needs recalling; "the CubeSat battery is 18650 Li-ion"
is not, and does. This module is the filter between the two (ADR 0027).

It is deliberately a set of explicit, inspectable rules rather than an
LLM judgment call. Rules cost nothing per turn, never vary between
identical inputs, and can be read and corrected by a human — and the one
signal that matters most is unambiguous anyway: the user saying
"remember this". An LLM-rated importance pass (as Stanford's original
design and Mem0 both use) is a natural later refinement, and slots in
behind this same function.
"""

from __future__ import annotations

import re

from runtime.memory.memory import DEFAULT_IMPORTANCE, MAX_IMPORTANCE, MemoryKind

# Said by a user who is deliberately committing something to memory.
# These pin the memory and max its importance — an explicit instruction
# outranks every heuristic here.
EXPLICIT_MARKERS: tuple[str, ...] = (
    "remember that",
    "remember this",
    "remember:",
    "don't forget",
    "do not forget",
    "keep in mind",
    "make a note",
    "note that",
    "for future reference",
    "from now on",
)

# Phrasings that mark a durable conclusion rather than passing chatter.
DECISION_MARKERS: tuple[str, ...] = (
    "we decided",
    "we agreed",
    "i decided",
    "let's go with",
    "we're going with",
    "the plan is",
    "settled on",
    "chose",
)

PREFERENCE_MARKERS: tuple[str, ...] = (
    "i prefer",
    "i like",
    "i don't like",
    "i hate",
    "i always",
    "i never",
    "my favorite",
    "please always",
    "please never",
)

TASK_MARKERS: tuple[str, ...] = (
    "i need to",
    "i have to",
    "todo",
    "to-do",
    "remind me",
    "still need",
    "next step",
    "unfinished",
)

# Requests that are pure device control or trivially re-derivable. These
# are the "just search again" cases: acting on them is the whole value,
# and a transcript of them is noise that buries everything else.
_TRIVIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(open|launch|start|run|close|quit|exit)\b"),
    re.compile(r"^\s*(play|pause|resume|stop|skip|next|previous|mute|unmute)\b"),
    # Permissive between the verb and the noun so every natural word
    # order matches: "turn up the volume", "turn the volume up", "set
    # volume to 50".
    re.compile(r"^\s*(turn|set)\b[\w\s]*\b(volume|brightness)\b"),
    re.compile(r"^\s*(volume|louder|quieter)\b"),
    re.compile(r"^\s*(switch to|show me|list)\b"),
    re.compile(r"^\s*(hi|hello|hey|thanks|thank you|ok|okay|yes|no|sure)\b\W*$"),
    re.compile(r"^\s*what('?s| is) the (time|date)\b"),
)

MIN_MEMORABLE_LENGTH = 12


def has_explicit_marker(text: str) -> bool:
    """Return whether `text` explicitly asks for something to be remembered."""
    lowered = text.lower()
    return any(marker in lowered for marker in EXPLICIT_MARKERS)


def is_trivial(text: str) -> bool:
    """Return whether `text` is a command or pleasantry not worth storing.

    An explicit "remember this" always wins: a user may legitimately ask
    for a device action to be remembered ("remember that I always open
    Spotify after VS Code"), and the instruction outranks the shape.
    """
    if has_explicit_marker(text):
        return False
    stripped = text.strip()
    if len(stripped) < MIN_MEMORABLE_LENGTH:
        return True
    lowered = stripped.lower()
    return any(pattern.search(lowered) for pattern in _TRIVIAL_PATTERNS)


def classify(text: str) -> MemoryKind:
    """Infer which `MemoryKind` best describes `text`."""
    lowered = text.lower()
    if any(marker in lowered for marker in PREFERENCE_MARKERS):
        return MemoryKind.PREFERENCE
    if any(marker in lowered for marker in DECISION_MARKERS):
        return MemoryKind.DECISION
    if any(marker in lowered for marker in TASK_MARKERS):
        return MemoryKind.TASK
    return MemoryKind.FACT


def score_importance(text: str, kind: MemoryKind) -> int:
    """Rate `text` from 1 to 10 for how much it deserves to be recalled.

    An explicit instruction to remember scores the maximum; decisions and
    preferences outrank bare facts, because they are the things a user
    notices an assistant forgetting.
    """
    if has_explicit_marker(text):
        return MAX_IMPORTANCE
    by_kind = {
        MemoryKind.DECISION: 8,
        MemoryKind.PREFERENCE: 7,
        MemoryKind.TASK: 7,
        MemoryKind.EVENT: 5,
        MemoryKind.FACT: DEFAULT_IMPORTANCE,
    }
    return by_kind.get(kind, DEFAULT_IMPORTANCE)
