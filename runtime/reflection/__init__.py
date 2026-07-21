"""Reflection: what Zeni concludes from what it remembers.

A layer *above* `runtime.memory`, never a modification of it (ADR 0029).
Raw memories stay immutable; reflections are separate, derived records
that reference the memories they came from, so every insight can be
traced back to its evidence and a wrong one can be deleted without
touching anything the user actually said.

Three levels, all through `ReflectionService`: a lightweight summary
when a meaningful conversation ends, a periodic deep synthesis across
everything accumulated, and a fresh analysis whenever the user asks.
See `docs/reflection.md`.
"""

from __future__ import annotations
