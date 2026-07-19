"""Tests for the EventBus."""

from __future__ import annotations

import logging

import pytest

from shared.events.bus import EventBus
from shared.events.event import Event
from shared.exceptions import EventBusError


class SampleEvent(Event):
    """A minimal concrete event used for bus tests."""


class OtherEvent(Event):
    """A second, distinct event type used to check type isolation."""


def test_emit_calls_subscribed_listener() -> None:
    bus = EventBus()
    received: list[Event] = []

    bus.subscribe(SampleEvent, received.append)
    event = SampleEvent(source="test")
    bus.emit(event)

    assert received == [event]


def test_emit_does_not_call_listener_of_other_type() -> None:
    bus = EventBus()
    received: list[Event] = []

    bus.subscribe(OtherEvent, received.append)
    bus.emit(SampleEvent(source="test"))

    assert received == []


def test_emit_with_no_listeners_does_not_raise() -> None:
    bus = EventBus()

    bus.emit(SampleEvent(source="test"))


def test_multiple_listeners_are_all_called() -> None:
    bus = EventBus()
    calls: list[str] = []

    bus.subscribe(SampleEvent, lambda event: calls.append("first"))
    bus.subscribe(SampleEvent, lambda event: calls.append("second"))
    bus.emit(SampleEvent(source="test"))

    assert calls == ["first", "second"]


def test_listeners_are_called_in_subscription_order() -> None:
    bus = EventBus()
    order: list[int] = []

    for i in range(5):
        bus.subscribe(SampleEvent, lambda event, i=i: order.append(i))
    bus.emit(SampleEvent(source="test"))

    assert order == [0, 1, 2, 3, 4]


def test_duplicate_listener_is_called_once_per_subscription() -> None:
    bus = EventBus()
    calls: list[Event] = []

    def listener(event: Event) -> None:
        calls.append(event)

    bus.subscribe(SampleEvent, listener)
    bus.subscribe(SampleEvent, listener)
    bus.emit(SampleEvent(source="test"))

    assert len(calls) == 2


def test_unsubscribe_removes_listener() -> None:
    bus = EventBus()
    received: list[Event] = []

    def listener(event: Event) -> None:
        received.append(event)

    bus.subscribe(SampleEvent, listener)
    bus.unsubscribe(SampleEvent, listener)
    bus.emit(SampleEvent(source="test"))

    assert received == []


def test_unsubscribe_removes_only_one_duplicate_subscription() -> None:
    bus = EventBus()
    calls: list[Event] = []

    def listener(event: Event) -> None:
        calls.append(event)

    bus.subscribe(SampleEvent, listener)
    bus.subscribe(SampleEvent, listener)
    bus.unsubscribe(SampleEvent, listener)
    bus.emit(SampleEvent(source="test"))

    assert len(calls) == 1


def test_unsubscribe_unknown_listener_raises() -> None:
    bus = EventBus()

    with pytest.raises(EventBusError):
        bus.unsubscribe(SampleEvent, lambda event: None)


def test_unsubscribe_from_never_subscribed_type_raises() -> None:
    bus = EventBus()

    def listener(event: Event) -> None:
        pass

    with pytest.raises(EventBusError):
        bus.unsubscribe(OtherEvent, listener)


def test_clear_removes_all_subscriptions() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe(SampleEvent, received.append)

    bus.clear()
    bus.emit(SampleEvent(source="test"))

    assert received == []


def test_failing_listener_does_not_stop_others() -> None:
    bus = EventBus()
    calls: list[str] = []

    def failing_listener(event: Event) -> None:
        raise ValueError("boom")

    bus.subscribe(SampleEvent, failing_listener)
    bus.subscribe(SampleEvent, lambda event: calls.append("second"))
    bus.emit(SampleEvent(source="test"))

    assert calls == ["second"]


def test_failing_listener_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.event_bus.failure")
    bus = EventBus(logger=logger)

    def failing_listener(event: Event) -> None:
        raise ValueError("boom")

    bus.subscribe(SampleEvent, failing_listener)

    with caplog.at_level(logging.ERROR, logger="test.event_bus.failure"):
        bus.emit(SampleEvent(source="test"))

    assert any("failed" in message for message in caplog.messages)


def test_emit_logs_event(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test.event_bus.emit")
    bus = EventBus(logger=logger)

    with caplog.at_level(logging.INFO, logger="test.event_bus.emit"):
        bus.emit(SampleEvent(source="test-source"))

    assert any("SampleEvent" in message and "test-source" in message for message in caplog.messages)
