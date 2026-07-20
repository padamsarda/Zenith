"""ClaudeProvider: Zenith's first real AssistantProvider (ADR 0015).

Calls the Anthropic Messages API directly over `urllib` — no `anthropic`
SDK dependency, per this repository's standard-library-only policy.
`generate_turn` is the provider's one contractual obligation (ADR 0011):
compose a Messages API request from the `TurnBrief`, send it through
`ClaudeTransport`, and translate the response back into an
`AssistantTurn`. Everything provider-specific — authentication, request
shape, retries, streaming, tool-call bookkeeping — stays inside this
module and its two siblings (`claude_transport.py`, `claude_messages.py`);
the engine and pipeline need no changes to use it.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from runtime.exceptions import AssistantProviderError
from runtime.providers.base import AssistantProvider, AssistantTurn, TurnBrief
from runtime.providers.claude_messages import (
    ToolCallCache,
    build_claude_messages,
    build_tools_payload,
    parse_turn,
)
from runtime.providers.claude_transport import ClaudeTransport, ClaudeTransportConfig

DEFAULT_LOGGER_NAME = "zenith.assistant.claude"
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_MAX_TOKENS = 4096
API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"


@dataclass(frozen=True)
class ClaudeUsage:
    """Cumulative token accounting across every call a provider has made."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    requests: int = 0

    def add(self, usage: dict[str, Any]) -> ClaudeUsage:
        """Return a new `ClaudeUsage` with `usage`'s counts folded in."""
        return ClaudeUsage(
            input_tokens=self.input_tokens + int(usage.get("input_tokens", 0) or 0),
            output_tokens=self.output_tokens + int(usage.get("output_tokens", 0) or 0),
            cache_creation_input_tokens=self.cache_creation_input_tokens
            + int(usage.get("cache_creation_input_tokens", 0) or 0),
            cache_read_input_tokens=self.cache_read_input_tokens
            + int(usage.get("cache_read_input_tokens", 0) or 0),
            requests=self.requests + 1,
        )


class ClaudeProvider(AssistantProvider):
    """Produces assistant turns by calling the Claude Messages API.

    Turns are stateless HTTP calls — there is no server-side "session" to
    create or resume; the conversation the API sees IS the request
    payload, rebuilt from `TurnBrief.messages` on every call, the same
    "assembled, not stored" principle ADR 0010 applies to context. Tools
    the `CapabilityCatalog` reports are translated into Claude's tool
    schema on every call too, so newly registered tools are visible on
    the model's very next turn with no provider-side refresh step.

    `stream` controls whether a call uses server-sent events internally;
    either way `generate_turn` still returns one complete `AssistantTurn`,
    since nothing in the pipeline consumes partial output yet (ADR 0012
    defers streaming responses at the engine level). Streaming is
    recommended for large `max_tokens` values, where Anthropic's own
    guidance is to avoid one long blocking read.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        stream: bool = False,
        provider_id: str = "claude",
        transport: ClaudeTransport | None = None,
        transport_config: ClaudeTransportConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Create a ClaudeProvider.

        Raises:
            AssistantProviderError: If no API key was given and
                `ANTHROPIC_API_KEY` is not set — credentials are resolved
                here, inside the implementation, never stored by the
                runtime (ADR 0011).
        """
        resolved_key = api_key or os.environ.get(API_KEY_ENV_VAR)
        if not resolved_key:
            raise AssistantProviderError(
                f"No Claude API key: pass api_key= or set {API_KEY_ENV_VAR}."
            )
        self._provider_id = provider_id
        self._model = model
        self._max_tokens = max_tokens
        self._stream = stream
        self._logger = logger or logging.getLogger(DEFAULT_LOGGER_NAME)
        self._transport = transport or ClaudeTransport(
            transport_config or ClaudeTransportConfig(api_key=resolved_key), logger=self._logger
        )
        self._tool_calls = ToolCallCache()
        self.usage = ClaudeUsage()

    @property
    def provider_id(self) -> str:
        """Stable identifier for this provider."""
        return self._provider_id

    @property
    def name(self) -> str:
        """Human-readable display name."""
        return "Claude"

    def generate_turn(self, brief: TurnBrief) -> AssistantTurn:
        """Produce the next assistant turn by calling the Messages API.

        Raises:
            AssistantProviderError: If the request fails, or Claude
                returns a turn with neither text nor tool calls.
        """
        system, claude_messages = build_claude_messages(brief.messages, self._tool_calls)
        combined_system = "\n\n".join(part for part in (brief.instructions, system) if part) or None
        tools_payload = build_tools_payload(brief.catalog)

        payload: dict[str, Any] = {
            "model": brief.metadata.get("model", self._model),
            "max_tokens": brief.metadata.get("max_tokens", self._max_tokens),
            "messages": claude_messages,
        }
        if combined_system:
            payload["system"] = combined_system
        if tools_payload:
            payload["tools"] = tools_payload
        if self._stream:
            payload["stream"] = True

        self._logger.info(
            "Requesting a Claude turn (model=%s, messages=%d, tools=%d).",
            payload["model"],
            len(claude_messages),
            len(tools_payload or []),
        )
        response = self._transport.send(payload)
        text, tool_calls = parse_turn(response, self._tool_calls)
        self._record_usage(response)
        self._warn_if_truncated(response)

        if text is None and not tool_calls:
            raise AssistantProviderError("Claude returned a turn with no text or tool calls.")
        return AssistantTurn(text=text, tool_calls=tool_calls)

    def _record_usage(self, response: dict[str, Any]) -> None:
        """Fold `response`'s usage into the running total, and log both."""
        usage = response.get("usage") or {}
        self.usage = self.usage.add(usage)
        self._logger.info(
            "Claude usage: +%s input / +%s output token(s) "
            "(cumulative %s/%s over %d request(s)).",
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            self.usage.input_tokens,
            self.usage.output_tokens,
            self.usage.requests,
        )

    def _warn_if_truncated(self, response: dict[str, Any]) -> None:
        """Log a warning when Claude's reply was cut off at the token limit."""
        if response.get("stop_reason") == "max_tokens":
            self._logger.warning(
                "Claude's reply was truncated at max_tokens=%s; consider raising it.",
                self._max_tokens,
            )
