"""EchoProvider: the built-in placeholder provider."""

from __future__ import annotations

from runtime.conversation.message import MessageRole
from runtime.exceptions import AssistantProviderError
from runtime.providers.base import AssistantProvider, AssistantTurn, TurnBrief


class EchoProvider(AssistantProvider):
    """Echoes the latest user message back as the assistant's turn.

    This is deliberately not intelligence — it is the provider the
    runtime registers at startup so the whole pipeline (conversation,
    assembly, engine, events, console) is exercisable end-to-end before
    any real integration exists. Replacing it with a real provider is
    configuration (`assistant_provider` in `config.toml`), not code
    change.
    """

    @property
    def provider_id(self) -> str:
        return "echo"

    @property
    def name(self) -> str:
        return "Echo"

    def generate_turn(self, brief: TurnBrief) -> AssistantTurn:
        """Return a turn echoing the brief's most recent USER message.

        Raises:
            AssistantProviderError: If the brief contains no user message.
        """
        for message in reversed(brief.messages):
            if message.role is MessageRole.USER:
                return AssistantTurn(text=f"You said: {message.content}")
        raise AssistantProviderError("EchoProvider needs at least one user message.")
