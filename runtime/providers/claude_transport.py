"""HTTP transport for the Claude Messages API.

Standard-library only (ADR 0015): requests are built and sent with
`urllib.request`, never the `anthropic` SDK. `ClaudeTransport.send`
normalizes both a plain JSON response and a streamed one into the same
shape (see `claude_stream.consume_event_stream`), so `ClaudeProvider`
reads one response format regardless of transport mode.
"""

from __future__ import annotations

import json
import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from runtime.exceptions import AssistantProviderError
from runtime.providers.claude_stream import consume_event_stream

DEFAULT_LOGGER_NAME = "zenith.assistant.claude"
DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 529})


class HTTPResponseLike(Protocol):
    """The subset of `http.client.HTTPResponse` the transport depends on.

    Named as a Protocol so tests can supply a fake response without
    performing real network I/O.
    """

    def __enter__(self) -> "HTTPResponseLike": ...

    def __exit__(self, *exc_info: object) -> None: ...

    def read(self) -> bytes: ...

    def __iter__(self): ...


Opener = Callable[[Request, float], HTTPResponseLike]


def default_opener(request: Request, timeout: float) -> HTTPResponseLike:
    """Send `request` with `urllib.request.urlopen`."""
    return urlopen(request, timeout=timeout)


@dataclass(frozen=True)
class ClaudeTransportConfig:
    """Everything `ClaudeTransport` needs to reach the Messages API.

    `opener` and `sleep` are the injectable seams: tests supply fakes so
    no suite ever performs real network I/O or waits on a real clock.
    """

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    anthropic_version: str = DEFAULT_ANTHROPIC_VERSION
    timeout_seconds: float = 60.0
    max_retries: int = 3
    backoff_seconds: float = 1.0
    opener: Opener = default_opener
    sleep: Callable[[float], None] = time.sleep


class ClaudeTransport:
    """Sends one Messages API request, with retries, timeouts, and streaming."""

    def __init__(
        self, config: ClaudeTransportConfig, logger: logging.Logger | None = None
    ) -> None:
        self._config = config
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)

    def send(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST `payload` to `/v1/messages` and return a normalized response.

        Retries on `RETRYABLE_STATUS_CODES` and on network-level errors,
        up to `config.max_retries` times, with exponential backoff (or
        the server's `retry-after`, when present).

        Raises:
            AssistantProviderError: On timeout, network failure, a
                non-retryable HTTP error, or once retries are exhausted.
        """
        streaming = bool(payload.get("stream"))
        body = json.dumps(payload).encode("utf-8")
        attempt = 0
        while True:
            attempt += 1
            try:
                with self._config.opener(self._build_request(body), self._config.timeout_seconds) as response:
                    if streaming:
                        return consume_event_stream(_decode_lines(response))
                    return _read_json(response)
            except HTTPError as exc:
                if attempt > self._config.max_retries or exc.code not in RETRYABLE_STATUS_CODES:
                    raise AssistantProviderError(
                        f"Claude API error {exc.code}: {_error_detail(exc)}"
                    ) from exc
                delay = _retry_after(exc) or self._backoff(attempt)
                self._logger.warning(
                    "Claude API returned %s (attempt %d/%d); retrying in %.1fs.",
                    exc.code, attempt, self._config.max_retries, delay,
                )
                self._config.sleep(delay)
            except (URLError, socket.timeout, TimeoutError) as exc:
                if attempt > self._config.max_retries:
                    raise AssistantProviderError(f"Claude API request failed: {exc}") from exc
                self._logger.warning(
                    "Claude API request error (attempt %d/%d): %s",
                    attempt, self._config.max_retries, exc,
                )
                self._config.sleep(self._backoff(attempt))

    def _build_request(self, body: bytes) -> Request:
        """Build the POST request for `body` against the Messages endpoint."""
        return Request(
            f"{self._config.base_url}/v1/messages",
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": self._config.api_key,
                "anthropic-version": self._config.anthropic_version,
            },
        )

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff for the given (1-indexed) attempt number."""
        return self._config.backoff_seconds * (2 ** (attempt - 1))


def _read_json(response: HTTPResponseLike) -> dict[str, Any]:
    """Read and parse a non-streaming JSON response body."""
    return json.loads(response.read().decode("utf-8"))


def _decode_lines(response: HTTPResponseLike):
    """Yield `response`'s lines as text, decoding bytes if necessary."""
    for raw_line in response:
        yield raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line


def _retry_after(exc: HTTPError) -> float | None:
    """Parse the `retry-after` header from an HTTPError, if present and valid."""
    header = exc.headers.get("retry-after") if exc.headers is not None else None
    if header is None:
        return None
    try:
        return float(header)
    except ValueError:
        return None


def _error_detail(exc: HTTPError) -> str:
    """Extract a human-readable message from an API error response body."""
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except (OSError, ValueError):
        return str(exc)
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and "message" in error:
        return str(error["message"])
    return str(body)
