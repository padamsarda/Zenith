"""In-process, synchronous event bus.

Listeners are plain callables registered against an event class. `emit`
calls every listener subscribed to the emitted event's exact type, in
subscription order, on the calling thread. There is no asyncio, no
threading, and no queueing.

Subscribing the same listener to the same event type more than once is
allowed and is not deduplicated: it will be called once per subscription.
Call `unsubscribe` the same number of times to fully remove it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from shared.events.event import Event
from shared.events.event_logger import EventLogger
from shared.exceptions import EventBusError

Listener = Callable[[Event], None]

DEFAULT_LOGGER_NAME = "zenith.events"


class EventBus:
    """Dispatches events to listeners subscribed to their exact type."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)
        self._event_logger = EventLogger(self._logger)
        self._listeners: dict[type[Event], list[Listener]] = {}

    def subscribe(self, event_type: type[Event], listener: Listener) -> None:
        """Register `listener` to be called whenever `event_type` is emitted."""
        self._listeners.setdefault(event_type, []).append(listener)

    def unsubscribe(self, event_type: type[Event], listener: Listener) -> None:
        """Remove one subscription of `listener` from `event_type`.

        Raises:
            EventBusError: If `listener` is not currently subscribed to
                `event_type`.
        """
        listeners = self._listeners.get(event_type)
        if not listeners or listener not in listeners:
            raise EventBusError(
                f"Listener {listener!r} is not subscribed to {event_type.__name__}."
            )
        listeners.remove(listener)

    def emit(self, event: Event) -> None:
        """Log `event`, then call every listener subscribed to its type.

        A listener that raises is logged and skipped; it does not stop
        remaining listeners from running.
        """
        self._event_logger.log(event)

        for listener in list(self._listeners.get(type(event), [])):
            try:
                listener(event)
            except Exception:
                self._logger.exception(
                    "Listener %r failed while handling %s", listener, event.name
                )

    def clear(self) -> None:
        """Remove all subscriptions for every event type."""
        self._listeners.clear()
