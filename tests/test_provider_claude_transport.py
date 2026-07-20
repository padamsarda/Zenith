"""Tests for ClaudeTransport, the stdlib HTTP transport to the Claude API."""

from __future__ import annotations

import json
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

from runtime.exceptions import AssistantProviderError
from runtime.providers.claude_transport import ClaudeTransport, ClaudeTransportConfig


class FakeResponse:
    """A minimal HTTPResponseLike double: a body, and optional SSE lines."""

    def __init__(self, body: bytes = b"", lines: list[bytes] | None = None) -> None:
        self._body = body
        self._lines = lines or []

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body

    def __iter__(self):
        return iter(self._lines)


class FakeOpener:
    """An Opener double that plays back a scripted queue of responses/errors."""

    def __init__(self) -> None:
        self.requests: list[tuple[Request, float]] = []
        self._queue: list[object] = []

    def queue(self, item: object) -> None:
        self._queue.append(item)

    def __call__(self, request: Request, timeout: float) -> FakeResponse:
        self.requests.append((request, timeout))
        item = self._queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def json_response(payload: dict) -> FakeResponse:
    return FakeResponse(body=json.dumps(payload).encode("utf-8"))


def http_error(code: int, body: dict, headers: dict[str, str] | None = None) -> HTTPError:
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return HTTPError(
        "https://api.anthropic.com/v1/messages", code, "error", message,
        BytesIO(json.dumps(body).encode("utf-8")),
    )


def make_transport(opener: FakeOpener, **overrides) -> ClaudeTransport:
    config = ClaudeTransportConfig(
        api_key="sk-test", opener=opener, sleep=lambda seconds: None, backoff_seconds=0.01,
        **overrides,
    )
    return ClaudeTransport(config)


def test_send_posts_to_the_messages_endpoint_with_expected_headers() -> None:
    opener = FakeOpener()
    opener.queue(json_response({"content": [], "usage": {}, "stop_reason": "end_turn"}))
    transport = make_transport(opener)

    transport.send({"model": "claude-sonnet-5", "messages": []})

    request, timeout = opener.requests[0]
    assert request.full_url == "https://api.anthropic.com/v1/messages"
    assert request.get_header("X-api-key") == "sk-test"
    assert request.get_header("Anthropic-version")
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == {"model": "claude-sonnet-5", "messages": []}
    assert timeout == 60.0


def test_send_returns_the_parsed_json_body() -> None:
    opener = FakeOpener()
    opener.queue(json_response({"content": [{"type": "text", "text": "hi"}], "usage": {"input_tokens": 1}, "stop_reason": "end_turn"}))
    transport = make_transport(opener)

    result = transport.send({"model": "x"})

    assert result["content"] == [{"type": "text", "text": "hi"}]
    assert result["usage"] == {"input_tokens": 1}


def test_send_retries_on_retryable_status_then_succeeds() -> None:
    opener = FakeOpener()
    opener.queue(http_error(529, {"error": {"message": "overloaded"}}))
    opener.queue(json_response({"content": [], "usage": {}, "stop_reason": "end_turn"}))
    sleeps: list[float] = []
    config = ClaudeTransportConfig(
        api_key="sk-test", opener=opener, sleep=sleeps.append, backoff_seconds=0.01, max_retries=3,
    )
    transport = ClaudeTransport(config)

    result = transport.send({"model": "x"})

    assert result["stop_reason"] == "end_turn"
    assert len(sleeps) == 1


def test_send_uses_retry_after_header_when_present() -> None:
    opener = FakeOpener()
    opener.queue(http_error(429, {"error": {"message": "slow down"}}, headers={"retry-after": "12"}))
    opener.queue(json_response({"content": [], "usage": {}, "stop_reason": "end_turn"}))
    sleeps: list[float] = []
    config = ClaudeTransportConfig(api_key="sk", opener=opener, sleep=sleeps.append, backoff_seconds=99.0)
    transport = ClaudeTransport(config)

    transport.send({"model": "x"})

    assert sleeps == [12.0]


def test_send_does_not_retry_non_retryable_status() -> None:
    opener = FakeOpener()
    opener.queue(http_error(400, {"error": {"message": "bad request"}}))
    transport = make_transport(opener)

    with pytest.raises(AssistantProviderError, match="bad request"):
        transport.send({"model": "x"})
    assert len(opener.requests) == 1


def test_send_raises_after_exhausting_retries() -> None:
    opener = FakeOpener()
    for _ in range(3):
        opener.queue(http_error(503, {"error": {"message": "unavailable"}}))
    transport = make_transport(opener, max_retries=2)

    with pytest.raises(AssistantProviderError, match="unavailable"):
        transport.send({"model": "x"})
    assert len(opener.requests) == 3


def test_send_retries_on_network_error_then_succeeds() -> None:
    opener = FakeOpener()
    opener.queue(URLError("timed out"))
    opener.queue(json_response({"content": [], "usage": {}, "stop_reason": "end_turn"}))
    sleeps: list[float] = []
    config = ClaudeTransportConfig(api_key="sk", opener=opener, sleep=sleeps.append, backoff_seconds=0.01)
    transport = ClaudeTransport(config)

    result = transport.send({"model": "x"})

    assert result["stop_reason"] == "end_turn"
    assert len(sleeps) == 1


def test_send_raises_on_persistent_network_error() -> None:
    opener = FakeOpener()
    for _ in range(4):
        opener.queue(URLError("timed out"))
    transport = make_transport(opener, max_retries=3)

    with pytest.raises(AssistantProviderError, match="timed out"):
        transport.send({"model": "x"})


def test_send_streaming_returns_normalized_dict() -> None:
    lines = [
        b'event: content_block_start\n',
        b'data: {"index": 0, "content_block": {"type": "text", "text": ""}}\n',
        b'\n',
        b'event: content_block_delta\n',
        b'data: {"index": 0, "delta": {"type": "text_delta", "text": "hi"}}\n',
        b'\n',
        b'event: message_delta\n',
        b'data: {"delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 3}}\n',
        b'\n',
    ]
    opener = FakeOpener()
    opener.queue(FakeResponse(lines=lines))
    transport = make_transport(opener)

    result = transport.send({"model": "x", "stream": True})

    assert result["content"] == [{"type": "text", "text": "hi"}]
    assert result["stop_reason"] == "end_turn"
    assert result["usage"] == {"output_tokens": 3}


def test_error_detail_falls_back_to_str_when_body_is_not_json() -> None:
    opener = FakeOpener()
    error = HTTPError(
        "https://api.anthropic.com/v1/messages", 400, "Bad Request", Message(), BytesIO(b"not json"),
    )
    opener.queue(error)
    transport = make_transport(opener)

    with pytest.raises(AssistantProviderError, match="400"):
        transport.send({"model": "x"})
