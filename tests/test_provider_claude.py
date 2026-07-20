"""Tests for ClaudeProvider."""

from __future__ import annotations

import logging

import pytest

from runtime.capabilities.catalog import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
)
from runtime.conversation.message import Message, MessageRole
from runtime.exceptions import AssistantProviderError
from runtime.providers.base import TurnBrief
from runtime.providers.claude import ClaudeProvider
from shared.utils.uuid_utils import generate_id


class FakeTransport:
    """A ClaudeTransport double that plays back queued responses."""

    def __init__(self) -> None:
        self.sent_payloads: list[dict] = []
        self._responses: list[dict] = []

    def queue(self, response: dict) -> None:
        self._responses.append(response)

    def send(self, payload: dict) -> dict:
        self.sent_payloads.append(payload)
        return self._responses.pop(0)


def make_brief(
    messages: tuple[Message, ...] = (),
    *,
    instructions: str | None = None,
    catalog: CapabilityCatalog | None = None,
    metadata: dict | None = None,
) -> TurnBrief:
    return TurnBrief(
        conversation_id=generate_id(),
        messages=messages,
        instructions=instructions,
        catalog=catalog or CapabilityCatalog(tools=(), skills=()),
        metadata=metadata or {},
    )


def make_provider(transport: FakeTransport, **overrides) -> ClaudeProvider:
    return ClaudeProvider(api_key="sk-test", transport=transport, **overrides)


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(AssistantProviderError):
        ClaudeProvider()


def test_api_key_resolved_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")

    provider = ClaudeProvider()

    assert provider.provider_id == "claude"


def test_provider_identity() -> None:
    provider = make_provider(FakeTransport())

    assert provider.provider_id == "claude"
    assert provider.name == "Claude"


def test_generate_turn_sends_expected_payload() -> None:
    transport = FakeTransport()
    transport.queue(
        {"content": [{"type": "text", "text": "hi there"}], "usage": {}, "stop_reason": "end_turn"}
    )
    provider = make_provider(transport, model="claude-sonnet-5", max_tokens=123)
    brief = make_brief((Message(role=MessageRole.USER, content="hello"),))

    turn = provider.generate_turn(brief)

    assert turn.text == "hi there"
    assert turn.tool_calls == ()
    payload = transport.sent_payloads[0]
    assert payload["model"] == "claude-sonnet-5"
    assert payload["max_tokens"] == 123
    assert payload["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
    assert "tools" not in payload
    assert "system" not in payload
    assert "stream" not in payload


def test_generate_turn_includes_skill_instructions_as_system() -> None:
    transport = FakeTransport()
    transport.queue({"content": [{"type": "text", "text": "ok"}], "usage": {}, "stop_reason": "end_turn"})
    provider = make_provider(transport)
    brief = make_brief((Message(role=MessageRole.USER, content="hi"),), instructions="Be terse.")

    provider.generate_turn(brief)

    assert transport.sent_payloads[0]["system"] == "Be terse."


def test_generate_turn_includes_tools_payload_when_catalog_has_tools() -> None:
    transport = FakeTransport()
    transport.queue({"content": [{"type": "text", "text": "ok"}], "usage": {}, "stop_reason": "end_turn"})
    provider = make_provider(transport)
    descriptor = CapabilityDescriptor(
        kind=CapabilityKind.TOOL, capability_id="clock", name="Clock", description="Tells time."
    )
    brief = make_brief(
        (Message(role=MessageRole.USER, content="hi"),),
        catalog=CapabilityCatalog(tools=(descriptor,), skills=()),
    )

    provider.generate_turn(brief)

    tools = transport.sent_payloads[0]["tools"]
    assert tools[0]["name"] == "clock"


def test_generate_turn_returns_tool_calls() -> None:
    transport = FakeTransport()
    transport.queue(
        {
            "content": [{"type": "tool_use", "name": "clock", "input": {}}],
            "usage": {},
            "stop_reason": "tool_use",
        }
    )
    provider = make_provider(transport)
    brief = make_brief((Message(role=MessageRole.USER, content="what time"),))

    turn = provider.generate_turn(brief)

    assert turn.text is None
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].tool_id == "clock"


def test_generate_turn_reconstructs_prior_tool_call_on_next_request() -> None:
    transport = FakeTransport()
    transport.queue(
        {
            "content": [{"type": "tool_use", "name": "clock", "input": {"tz": "UTC"}}],
            "usage": {},
            "stop_reason": "tool_use",
        }
    )
    provider = make_provider(transport)
    first_turn = provider.generate_turn(make_brief((Message(role=MessageRole.USER, content="what time"),)))
    call = first_turn.tool_calls[0]

    transport.queue({"content": [{"type": "text", "text": "It is noon."}], "usage": {}, "stop_reason": "end_turn"})
    history = (
        Message(role=MessageRole.USER, content="what time"),
        Message(
            role=MessageRole.TOOL,
            content="12:00",
            metadata={"tool_id": "clock", "call_id": str(call.call_id)},
        ),
    )

    provider.generate_turn(make_brief(history))

    second_payload = transport.sent_payloads[1]
    assistant_message = second_payload["messages"][1]
    assert assistant_message["content"][0]["input"] == {"tz": "UTC"}


def test_generate_turn_raises_when_no_text_or_tool_calls() -> None:
    transport = FakeTransport()
    transport.queue({"content": [], "usage": {}, "stop_reason": "end_turn"})
    provider = make_provider(transport)

    with pytest.raises(AssistantProviderError):
        provider.generate_turn(make_brief((Message(role=MessageRole.USER, content="hi"),)))


def test_usage_accumulates_across_calls() -> None:
    transport = FakeTransport()
    transport.queue(
        {"content": [{"type": "text", "text": "a"}], "usage": {"input_tokens": 5, "output_tokens": 2}, "stop_reason": "end_turn"}
    )
    transport.queue(
        {"content": [{"type": "text", "text": "b"}], "usage": {"input_tokens": 3, "output_tokens": 1}, "stop_reason": "end_turn"}
    )
    provider = make_provider(transport)
    brief = make_brief((Message(role=MessageRole.USER, content="hi"),))

    provider.generate_turn(brief)
    provider.generate_turn(brief)

    assert provider.usage.input_tokens == 8
    assert provider.usage.output_tokens == 3
    assert provider.usage.requests == 2


def test_metadata_overrides_model_and_max_tokens() -> None:
    transport = FakeTransport()
    transport.queue({"content": [{"type": "text", "text": "ok"}], "usage": {}, "stop_reason": "end_turn"})
    provider = make_provider(transport, model="claude-sonnet-5", max_tokens=100)
    brief = make_brief(
        (Message(role=MessageRole.USER, content="hi"),),
        metadata={"model": "claude-opus-4-8", "max_tokens": 999},
    )

    provider.generate_turn(brief)

    payload = transport.sent_payloads[0]
    assert payload["model"] == "claude-opus-4-8"
    assert payload["max_tokens"] == 999


def test_stream_flag_is_included_when_enabled() -> None:
    transport = FakeTransport()
    transport.queue({"content": [{"type": "text", "text": "ok"}], "usage": {}, "stop_reason": "end_turn"})
    provider = make_provider(transport, stream=True)

    provider.generate_turn(make_brief((Message(role=MessageRole.USER, content="hi"),)))

    assert transport.sent_payloads[0]["stream"] is True


def test_truncation_logs_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    transport = FakeTransport()
    transport.queue({"content": [{"type": "text", "text": "cut off"}], "usage": {}, "stop_reason": "max_tokens"})
    provider = make_provider(transport)

    with caplog.at_level(logging.WARNING, logger="zenith.assistant.claude"):
        provider.generate_turn(make_brief((Message(role=MessageRole.USER, content="hi"),)))

    assert any("truncated" in record.getMessage() for record in caplog.records)
