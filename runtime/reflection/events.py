"""Concrete events emitted by the reflection layer."""

from __future__ import annotations

from dataclasses import dataclass

from shared.events.event import Event


@dataclass(frozen=True)
class ReflectionCreated(Event):
    """A reflection was stored. Payload: `reflection_id`, `kind`, `generation`, `sources`."""


@dataclass(frozen=True)
class ReflectionDeleted(Event):
    """A reflection was deleted. Payload: `reflection_id`."""


@dataclass(frozen=True)
class ReflectionSkipped(Event):
    """Reflection was considered and declined. Payload: `kind`, `reason`.

    Emitted rather than staying silent because "nothing happened" and
    "nothing was worth reflecting on" are different states, and only one
    of them indicates a problem.
    """
