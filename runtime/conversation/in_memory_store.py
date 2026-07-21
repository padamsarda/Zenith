"""InMemoryConversationStore: the default, non-durable ConversationStore."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from runtime.conversation.conversation import Conversation
from runtime.conversation.events import (
    ConversationArchived,
    ConversationStarted,
    MessageAppended,
)
from runtime.conversation.state import ConversationState
from runtime.conversation.store import SOURCE, ConversationStore
from runtime.exceptions import ConversationNotFoundError

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.conversation.message import Message


class InMemoryConversationStore(ConversationStore):
    """Holds conversations in a plain dict; nothing survives a restart.

    `ApplicationContext.conversations`'s default — harmless scaffolding
    in the same role `EchoProvider` plays for assistant providers, so
    the pipeline is exercisable with zero setup. An integrator who wants
    conversation history to survive a restart assigns
    `runtime.conversation.sqlite.store.SQLiteConversationStore` onto
    `context.conversations` instead, the same way `ClaudeProvider` (ADR
    0015) or a `runtime.tools` tool is wired in — not a config flag,
    since a durable backend is deployment code, not a toggle.
    """

    def __init__(self) -> None:
        self._conversations: dict[UUID, Conversation] = {}

    def create(
        self,
        application_context: ApplicationContext,
        *,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation:
        conversation = Conversation(title=title, metadata=metadata)
        self._conversations[conversation.conversation_id] = conversation
        application_context.events.emit(
            ConversationStarted(
                source=SOURCE,
                payload={
                    "conversation_id": str(conversation.conversation_id),
                    "title": conversation.title,
                },
            )
        )
        return conversation

    def get(self, conversation_id: UUID) -> Conversation:
        try:
            return self._conversations[conversation_id]
        except KeyError:
            raise ConversationNotFoundError(
                f"Conversation {conversation_id} is not in the store."
            ) from None

    def has(self, conversation_id: UUID) -> bool:
        return conversation_id in self._conversations

    def list(self) -> list[Conversation]:
        return list(self._conversations.values())

    def append(
        self,
        conversation_id: UUID,
        message: Message,
        application_context: ApplicationContext,
    ) -> None:
        conversation = self.get(conversation_id)
        conversation.append(message)
        application_context.events.emit(
            MessageAppended(
                source=SOURCE,
                payload={
                    "conversation_id": str(conversation_id),
                    "message_id": str(message.message_id),
                    "role": message.role.name,
                },
            )
        )

    def archive(self, conversation_id: UUID, application_context: ApplicationContext) -> None:
        conversation = self.get(conversation_id)
        conversation.transition_to(ConversationState.ARCHIVED)
        application_context.events.emit(
            ConversationArchived(
                source=SOURCE,
                payload={"conversation_id": str(conversation_id)},
            )
        )
