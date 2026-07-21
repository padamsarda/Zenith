"""ConversationStore: the abstract contract every conversation backend implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from runtime.context import ApplicationContext
    from runtime.conversation.conversation import Conversation
    from runtime.conversation.message import Message

SOURCE = "conversation_store"


class ConversationStore(ABC):
    """The only path that creates, appends to, or archives a conversation.

    Every change goes through a `ConversationStore`, so every backend
    announces it on the `EventBus` the same way — a caller (the
    assistant engine, `ConsoleInterface`, any future interface) reads
    and writes conversations without knowing or caring which backend is
    behind `context.conversations`. `InMemoryConversationStore` is the
    scaffolding default; `runtime.conversation.sqlite.store.SQLiteConversationStore`
    is the durable one. Neither the assistant pipeline nor a caller
    changes when the concrete class does — this is ADR 0010's principle
    (context assembled from durable state, never cached) applied to
    which store holds that state.

    Mutating methods take `application_context` as a parameter, the same
    shape `PluginRegistry` and `CommandExecutor` use: a store built via
    `field(default_factory=...)` cannot hold a reference to the
    `ApplicationContext` that owns it, since it is constructed before the
    rest of the context exists.
    """

    @abstractmethod
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

    @abstractmethod
    def get(self, conversation_id: UUID) -> Conversation:
        """Return the conversation with `conversation_id`.

        Raises:
            ConversationNotFoundError: If no such conversation is stored.
        """

    @abstractmethod
    def has(self, conversation_id: UUID) -> bool:
        """Return True if a conversation with `conversation_id` is stored."""

    @abstractmethod
    def list(self) -> list[Conversation]:
        """Return a snapshot list of all stored conversations, oldest first."""

    @abstractmethod
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

    @abstractmethod
    def archive(self, conversation_id: UUID, application_context: ApplicationContext) -> None:
        """Archive the conversation with `conversation_id`.

        Emits `ConversationArchived` after a successful transition.

        Raises:
            ConversationNotFoundError: If no such conversation is stored.
            ConversationValidationError: If the conversation is already
                archived.
        """
