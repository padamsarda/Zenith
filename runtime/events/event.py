"""Base event type for the Zenith event system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from runtime.utils.time_utils import utc_now
from runtime.utils.uuid_utils import generate_id


@dataclass(frozen=True)
class Event:
    """Base class for all Zenith events.

    Every event carries a unique id, a UTC timestamp, a name (derived
    from its class), the name of what emitted it, and an optional
    payload of extra data. Concrete events are defined as subclasses
    with no additional fields required.
    """

    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: UUID = field(default_factory=generate_id)
    timestamp: datetime = field(default_factory=utc_now)

    @property
    def name(self) -> str:
        """The event's name, derived from its class name."""
        return type(self).__name__
