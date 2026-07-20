"""ConversationStore: holds conversations and mediates every change to them."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from runtime.conversation.conversation import Conversation
from runtime.conversation.events import (
    ConversationArchived,
    ConversationStarted,
    MessageAppended,
)
from runtime.conversation.message import Message
from runtime.conversation.state import ConversationState
from runtime.exceptions import ConversationNotFoundError

if TYPE_CHECKING:
    from runtime.context import ApplicationContext

SOURCE = "conversation_store"


class ConversationStore:
    """In-memory store of conversations, and the only path that changes them.

    Everything that creates, appends to, or archives a conversation goes
    through this store, so every change is announced on the `EventBus`
    the same way. Like `PluginRegistry`, the store cannot hold a
    reference to the `ApplicationContext` that owns it (it is built via
    `field(default_factory=ConversationStore)` before the rest of the
    context exists), so mutating methods take the context as a
    parameter — this is what gives the store access to the bus.

    The store is in-memory only: conversations do not survive a restart.
    Durable conversation history is a deliberate deferral — see
    `docs/assistant.md`.
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
        """Create, store, and return a new ACTIVE conversation.

        Emits `ConversationStarted`.
        """
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
        """Return the conversation with `conversation_id`.

        Raises:
            ConversationNotFoundError: If no such conversation is stored.
        """
        try:
            return self._conversations[conversation_id]
        except KeyError:
            raise ConversationNotFoundError(
                f"Conversation {conversation_id} is not in the store."
            ) from None

    def has(self, conversation_id: UUID) -> bool:
        """Return True if a conversation with `conversation_id` is stored."""
        return conversation_id in self._conversations

    def list(self) -> list[Conversation]:
        """Return a snapshot list of all stored conversations, oldest first."""
        return list(self._conversations.values())

    def append(
        self,
        conversation_id: UUID,
        message: Message,
        application_context: ApplicationContext,
    ) -> None:
        """Append `message` to the conversation with `conversation_id`.

        Emits `MessageAppended` after a successful append.

        Raises:
            ConversationNotFoundError: If no such conversation is stored.
            ConversationValidationError: If the conversation is not
                ACTIVE or the message fails validation.
        """
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

    def archive(
        self, conversation_id: UUID, application_context: ApplicationContext
    ) -> None:
        """Archive the conversation with `conversation_id`.

        Emits `ConversationArchived` after a successful transition.

        Raises:
            ConversationNotFoundError: If no such conversation is stored.
            ConversationValidationError: If the conversation is already
                archived.
        """
        conversation = self.get(conversation_id)
        conversation.transition_to(ConversationState.ARCHIVED)
        application_context.events.emit(
            ConversationArchived(
                source=SOURCE,
                payload={"conversation_id": str(conversation_id)},
            )
        )
