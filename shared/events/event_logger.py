"""Logs every event that passes through the EventBus."""

from __future__ import annotations

import logging

from shared.events.event import Event

DEFAULT_LOGGER_NAME = "zenith.events"


class EventLogger:
    """Writes a readable log line for each event it is given."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    def log(self, event: Event) -> None:
        """Log an event's timestamp, name, and source."""
        self._logger.info(
            "[%s] %s from %s",
            event.timestamp.isoformat(timespec="seconds"),
            event.name,
            event.source,
        )
