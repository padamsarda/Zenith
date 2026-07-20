"""AssistantProvider: the abstract contract every assistant AI integration implements.

This is the seam that keeps the Zenith runtime provider-independent.
The assistant pipeline never talks to Claude, Gemini, Codex, a local
model, or any other service directly — it only ever holds an
`AssistantProvider` and speaks this small, turn-oriented vocabulary:
here is the conversation so far and what you may use; give me the next
turn. Anything provider-specific (APIs, CLIs, credentials, prompt
formats) lives inside a concrete implementation.

This deliberately parallels the Engineering Manager's `Provider`
contract (ADR 0005) without sharing it: that contract's unit of work is
a long-running engineering *session* (start, check, resume, stop); this
one's is a single conversational *turn*. The vocabularies are disjoint,
so the two contracts stay separate — see ADR 0011. Like ADR 0005, the
contract is minimal and synchronous, and is expected to grow additively
(streaming, token accounting, richer capability negotiation) as real
integrations demand it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from runtime.capabilities.catalog import CapabilityCatalog
from runtime.conversation.message import Message
from shared.utils.uuid_utils import generate_id


@dataclass(frozen=True)
class ToolCall:
    """A provider's request that one tool be invoked.

    `call_id` links the eventual result message back to this call, so a
    turn with several calls remains unambiguous.
    """

    tool_id: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: UUID = field(default_factory=generate_id)


@dataclass(frozen=True)
class AssistantTurn:
    """What a provider produces for one turn.

    A turn carries text, tool calls, or both. Text alone ends the
    request; tool calls make the engine invoke each tool, record the
    results in the conversation, and ask the provider for another turn.
    A turn with neither is invalid — the engine rejects it via
    `runtime.assistant.validation.validate_turn`.
    """

    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True)
class TurnBrief:
    """Everything a provider is given to produce one turn.

    Composed deterministically by the `AssistantContextAssembler` from
    durable state — the conversation's messages, active skills'
    instructions, and the current capability catalog. `metadata` carries
    provider-specific options without the core contract having to know
    about them — the same extension pattern `Command.metadata` and the
    Engineering Manager's `SessionSpec.metadata` use.
    """

    conversation_id: UUID
    messages: tuple[Message, ...]
    instructions: str | None = None
    catalog: CapabilityCatalog = field(
        default_factory=lambda: CapabilityCatalog(tools=(), skills=())
    )
    metadata: dict[str, Any] = field(default_factory=dict)


class AssistantProvider(ABC):
    """Base class for every assistant AI integration.

    Implementations must be honest about failure: a turn that cannot be
    produced raises `AssistantProviderError` rather than returning an
    empty or misleading turn. Credentials are resolved inside the
    implementation, never stored in the runtime.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Stable identifier for this provider (e.g. "claude", "echo")."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable display name."""

    @abstractmethod
    def generate_turn(self, brief: TurnBrief) -> AssistantTurn:
        """Produce the assistant's next turn for `brief`.

        Raises:
            AssistantProviderError: If a turn cannot be produced.
        """
