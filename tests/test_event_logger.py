"""Tests for the EventLogger."""

from __future__ import annotations

import logging

import pytest

from shared.events.event import Event
from shared.events.event_logger import EventLogger


def test_log_writes_info_record(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.event_logger")
    event_logger = EventLogger(logger)

    with caplog.at_level(logging.INFO, logger="test.event_logger"):
        event_logger.log(Event(source="unit-test"))

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.INFO


def test_log_message_includes_name_and_source(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.event_logger.content")
    event_logger = EventLogger(logger)

    with caplog.at_level(logging.INFO, logger="test.event_logger.content"):
        event_logger.log(Event(source="unit-test"))

    message = caplog.records[0].getMessage()
    assert "Event" in message
    assert "unit-test" in message
