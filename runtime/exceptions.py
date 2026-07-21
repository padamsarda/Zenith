"""Exception hierarchy for the Zenith assistant runtime's subsystems.

Covers the service registry, command execution framework, plugin
framework, conversation model, capability registries, and the assistant
pipeline. These are specific to how this runtime models its subsystems,
so they live here rather than in `shared.exceptions` — a future
platform built on `shared` would not necessarily share these same
abstractions. Every class here still roots at
`shared.exceptions.ZenithError`. (`EventBusError` lives in
`shared.exceptions`, alongside the event system in `shared.events`.)
"""

from __future__ import annotations

from shared.exceptions import ZenithError


class ServiceRegistryError(ZenithError):
    """Base class for service registry errors."""


class ServiceNotFoundError(ServiceRegistryError):
    """Raised when looking up or removing a service that isn't registered."""


class ServiceAlreadyRegisteredError(ServiceRegistryError):
    """Raised when registering a service name that is already in use."""


class CommandError(ZenithError):
    """Base class for all command execution framework errors."""


class CommandValidationError(CommandError):
    """Raised when a Command fails validation.

    Covers structural issues (name, metadata), duplicate execution of an
    already-executed command ID, and invalid `CommandStatus` transitions.
    """


class CommandExecutionError(CommandError):
    """Raised by a command action to report a structured execution failure.

    The `CommandExecutor` treats this the same as any other exception
    raised from an action: it is caught, logged, and turned into a
    failed `CommandResult` rather than propagating.
    """


class CommandCancelledError(CommandError):
    """Raised by a command action to signal cooperative cancellation."""


class PluginError(ZenithError):
    """Base class for all plugin framework errors."""


class PluginRegistrationError(PluginError):
    """Raised when registering a plugin ID that is already registered."""


class PluginNotFoundError(PluginError):
    """Raised when looking up, unregistering, enabling, or disabling a
    plugin ID that isn't registered.
    """


class PluginValidationError(PluginError):
    """Raised when a Plugin fails validation.

    Covers structural issues (manifest fields, version format) and
    invalid `PluginState` transitions.
    """


class PluginLifecycleError(PluginError):
    """Raised when a Plugin's `initialize`, `shutdown`, `register`, or
    `unregister` hook raises during `PluginRegistry.register` or
    `PluginRegistry.unregister`. Wraps the original exception.
    """


class PluginLoadError(PluginError):
    """Raised by a single-plugin load helper when a plugin directory does
    not produce a usable `Plugin` (import failure, missing factory, or a
    factory that returns something other than a `Plugin`).

    `PluginLoader.load_all` catches this per plugin directory rather than
    letting it propagate, so one broken plugin cannot stop the rest from
    loading or the runtime from starting.
    """


class ConversationError(ZenithError):
    """Base class for all conversation model errors."""


class ConversationNotFoundError(ConversationError):
    """Raised when looking up, appending to, or archiving a conversation
    ID that the `ConversationStore` does not hold.
    """


class ConversationValidationError(ConversationError):
    """Raised when a Message or Conversation fails validation.

    Covers structural issues (role, content, metadata), invalid
    `ConversationState` transitions, and appending to a conversation
    that is no longer active.
    """


class ConversationStoreError(ConversationError):
    """Raised by a durable `ConversationStore` for a storage-layer failure
    that is not a `ConversationNotFoundError` or `ConversationValidationError`
    — a newer-than-supported schema, or a migration or query that failed
    for reasons the store itself did not cause (disk I/O, a corrupt
    database file). Mirrors the Engineering Manager's `StoreError`.
    """


class CapabilityError(ZenithError):
    """Base class for all capability (tool and skill) errors."""


class CapabilityValidationError(CapabilityError):
    """Raised when a Tool or Skill fails structural validation
    (identifier, name, description, or parameter declaration).
    """


class ToolRegistrationError(CapabilityError):
    """Raised when registering a tool ID that is already registered."""


class ToolNotFoundError(CapabilityError):
    """Raised when looking up or unregistering a tool ID that isn't
    registered. Mirrors `ServiceNotFoundError`.
    """


class SkillRegistrationError(CapabilityError):
    """Raised when registering a skill ID that is already registered."""


class SkillNotFoundError(CapabilityError):
    """Raised when looking up or unregistering a skill ID that isn't
    registered. Mirrors `ServiceNotFoundError`.
    """


class ToolExecutionError(CapabilityError):
    """Raised by a built-in `Tool` implementation when it cannot complete
    its action.

    Covers a tool's own domain-level guards (a Filesystem path escaping
    its sandbox root, a Git operation outside a repository, malformed
    arguments) as well as underlying OS/subprocess failures (the
    executable could not be started). `Tool.invoke` runs inside a
    `Command` action, so the `CommandExecutor` treats this the same as
    any other exception: caught, reported as a failed tool call, and
    never propagated out of the assistant pipeline.
    """


class MemoryError_(ZenithError):
    """Base class for all memory subsystem errors.

    Named with a trailing underscore to avoid shadowing the built-in
    `MemoryError`, following the same rule that gives the runtime
    `ZenithRuntimeError` rather than `RuntimeError`. Subclasses carry
    ordinary names, since none of them collides.
    """


class MemoryNotFoundError(MemoryError_):
    """Raised when looking up or forgetting a memory ID that isn't stored."""


class MemoryValidationError(MemoryError_):
    """Raised when a Memory fails structural validation (content,
    kind, importance range, tags, or access count).
    """


class MemoryStoreError(MemoryError_):
    """Raised by a durable `MemoryStore` for a storage-layer failure that
    is not a `MemoryNotFoundError` or `MemoryValidationError` — a
    newer-than-supported schema, a SQLite build without FTS5, or a
    migration or query that failed. Mirrors `ConversationStoreError`.
    """


class ReflectionError(ZenithError):
    """Base class for all reflection layer errors."""


class ReflectionNotFoundError(ReflectionError):
    """Raised when looking up or deleting a reflection ID that isn't stored."""


class ReflectionValidationError(ReflectionError):
    """Raised when a Reflection fails structural validation (content,
    kind, provenance, or generation).
    """


class ReflectionStoreError(ReflectionError):
    """Raised by a durable `ReflectionStore` for a storage-layer failure —
    a newer-than-supported schema, or a migration or query that failed.
    Mirrors `MemoryStoreError`.
    """


class AssistantError(ZenithError):
    """Base class for all assistant pipeline errors."""


class AssistantProviderError(AssistantError):
    """Raised by an `AssistantProvider` when it cannot produce a turn.

    The `AssistantEngine` treats this as an honest provider failure: it
    is caught, logged, and turned into a failed `AssistantResponse`
    rather than propagating.
    """


class AssistantProviderRegistrationError(AssistantError):
    """Raised when registering a provider ID that is already registered."""


class AssistantProviderNotFoundError(AssistantError):
    """Raised when looking up a provider ID that isn't registered."""


class RequestValidationError(AssistantError):
    """Raised when an AssistantRequest or AssistantTurn fails validation.

    Covers structural issues (text, metadata, turn shape) and invalid
    `RequestStatus` transitions.
    """


class ToolCallVetoedError(AssistantError):
    """Raised by a `before_tool` hook to block a tool call it did not approve.

    `ToolCallRunner` treats any exception from `before_tool` as a veto
    (ADR 0013); this is the typed one `ConfirmationHook`
    (`runtime.assistant.confirmation`) raises when a user declines a
    destructive action, so the reason recorded in the conversation reads
    as a decision, not an error.
    """
