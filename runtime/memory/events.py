"""Concrete events emitted by the memory subsystem."""

from __future__ import annotations

from shared.events.event import Event


class MemoryRemembered(Event):
    """A new memory was stored. Payload: `memory_id`, `kind`, `importance`, `pinned`."""


class MemoryUpdated(Event):
    """An existing memory was replaced. Payload: `memory_id`, `importance`."""


class MemoryForgotten(Event):
    """A memory was deleted. Payload: `memory_id`."""


class MemoriesRecalled(Event):
    """Memories were retrieved for a query. Payload: `query`, `count`, `window`."""
