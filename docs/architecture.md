# Runtime Architecture

This document describes the internal structure of the Zenith runtime —
one of the two applications in this repository (see ADR 0002; the other
is documented in `engineering_manager.md`). It covers what owns what,
and how control flows through startup and shutdown.

## Overview

```
main.py
  -> Runtime.run()
       -> Runtime.start()
       -> console session (config.interactive) or idle loop
       -> Runtime.stop()
```

`main.py` only constructs a `Runtime` and calls `run()`. All lifecycle
logic lives in `runtime.runtime.Runtime`.

## ApplicationContext

`runtime.context.ApplicationContext` is a single object that holds every
shared resource a subsystem might need:

- `config` — the current `Config` (see `configs/config.py`)
- `logger` — the runtime's logger
- `version` — the application version string
- `started_at` — a UTC timestamp set at context creation
- `state` — the current `RuntimeState`
- `services` — a `ServiceRegistry` (see `service_registry.md`)
- `events` — an `EventBus` (see `events.md`)
- `commands` — a `CommandExecutor` (see `commands.md`)
- `plugins` — a `PluginRegistry` (see `plugins.md`)
- `conversations` — a `ConversationStore` (see `assistant.md`)
- `memory` — a `MemoryStore` (see `memory.md`)
- `tools` — a `ToolRegistry` (see `assistant.md`)
- `skills` — a `SkillRegistry` (see `assistant.md`)
- `assistant_providers` — an `AssistantProviderRegistry` (see `assistant.md`)
- `assistant` — an `AssistantEngine` (see `assistant.md`)

`Runtime` owns exactly one `ApplicationContext` instance
(`Runtime.context`), created in `__init__`. Nothing in the codebase uses
module-level globals for shared state; anything that needs runtime
resources should be passed the context (or a specific field from it)
rather than importing shared state directly.

The context is a plain, mutable `dataclass` — not frozen — because
`state`, `config`, and `logger` are all updated in place as the runtime
moves through its lifecycle. This is the one place mutation is expected;
everything else (`Config`, `Event`) is immutable.

## RuntimeState

`runtime.state.RuntimeState` is an enum with six values:

`INITIALIZING -> STARTING -> RUNNING -> STOPPING -> STOPPED`, with
`FAILED` reachable from `STARTING` if startup cannot complete.

`Runtime.state` is a read-only property that returns
`self.context.state` — state lives in exactly one place.

## Startup sequence (`Runtime.start`)

1. `context.state = STARTING`; emit `ApplicationStarting`.
2. Load configuration (`configs.config.load_config`). On failure, emit
   `ConfigurationLoadFailed`, set `state = FAILED`, and re-raise. On
   success, validate the config and emit `ConfigurationLoaded`.
3. Configure logging (`runtime.logging_setup.configure_logging`) using
   `context.config.debug`.
4. Print the startup banner.
5. Verify the project's required top-level folders exist. On failure,
   emit `ApplicationStartupFailed`, set `state = FAILED`, and raise
   `ZenithRuntimeError`.
6. Initialize the assistant subsystem: register the built-in
   `EchoProvider` so the request pipeline is servable. Real providers
   are registered by plugins or startup integrations; the configured
   default (`config.assistant_provider`) may name one that arrives
   later, since resolution happens per request.
7. Load plugins: `PluginLoader` (`plugins.md`, ADR 0017) discovers
   `plugin.py` files under `base_path / "plugins"` and registers each
   one. A plugin that fails to load or register is logged and skipped —
   never fatal to startup.
8. If `on_start` was supplied to `Runtime.__init__`, call it with the
   fully initialized `ApplicationContext` (ADR 0025). This is the seam a
   specific deployment uses to register real providers, tools, permission
   policies, and hooks — `Runtime` itself calls whatever it was given and
   knows nothing about what runs. `main.py`'s `_wire_zeni` is the first
   user of this seam.
9. `context.state = RUNNING`; emit `ApplicationStarted`.

## Serving (`Runtime.run`)

`run()` starts the runtime, serves until finished, and stops. With
`config.interactive` set it serves a console session
(`runtime.console.ConsoleInterface`) that ends at EOF or an exit word;
otherwise it idles until interrupted. Ctrl+C triggers a graceful
shutdown either way, and `stop()` always runs.

## Shutdown sequence (`Runtime.stop`)

1. If already `STOPPED`, return (idempotent).
2. `context.state = STOPPING`; emit `ApplicationStopping`.
3. `context.state = STOPPED`; emit `ApplicationStopped`.

## Module map

| Module | Responsibility |
|---|---|
| `runtime/runtime.py` | Owns the lifecycle. `main.py` also depends on the specific providers/tools/policies/hooks it composes at startup through `Runtime`'s `on_start` seam (ADR 0025). |
| `runtime/context.py` | `ApplicationContext` dataclass. |
| `runtime/state.py` | `RuntimeState` enum. |
| `runtime/exceptions.py` | Exception hierarchy for the runtime's own subsystems (service registry, event bus, commands, plugins, conversations, capabilities, assistant). Rooted at `shared.exceptions.ZenithError`. |
| `runtime/console.py` | `ConsoleInterface`: the interactive text session. See `assistant.md`. |
| `runtime/logging_setup.py` | Console logging configuration. |
| `runtime/registry.py` | `ServiceRegistry`. |
| `runtime/validation.py` | Guard functions used at system boundaries. |
| `runtime/events/` | Concrete runtime lifecycle events. The event system itself (`Event`, `EventBus`, `EventLogger`) lives in `shared/events/` — see `events.md`. |
| `runtime/commands/` | `Command`, `CommandStatus`, `CommandResult`, `CommandContext`, `CommandExecutor`, and concrete command events. See `commands.md`. |
| `runtime/plugins/` | `Plugin`, `PluginState`, `PluginManifest`, `PluginContext`, `PluginRegistry`, `PluginLoader`, and concrete plugin events. See `plugins.md`. |
| `runtime/conversation/` | `Message`, `Conversation`, `ConversationState`, the `ConversationStore` ABC, `InMemoryConversationStore`, `SQLiteConversationStore` (ADR 0018), and concrete conversation events. See `assistant.md`. |
| `runtime/memory/` | `Memory`, the `MemoryStore` ABC, `InMemoryMemoryStore`, `SQLiteMemoryStore` (FTS5), retrieval scoring, temporal resolution, and salience rules (ADR 0027). See `memory.md`. |
| `runtime/capabilities/` | `Tool`, `Skill`, their registries, the `CapabilityCatalog`, and concrete capability events. See `assistant.md`. |
| `runtime/providers/` | `AssistantProvider`, `TurnBrief`, `AssistantTurn`, `ToolCall`, `AssistantProviderRegistry`, the built-in `EchoProvider` / `ScriptedProvider`, and `ClaudeProvider` (ADR 0015). See `assistant.md`. |
| `runtime/tools/` | `FilesystemTool`, `ShellTool`, `GitTool`, `DiffTool`, `TestRunnerTool`, `AppLauncherTool`, `MediaControlTool` (ADR 0024), and the shared `sandbox`/`process`/`arguments` helpers they build on (ADR 0016). See `assistant.md`. |
| `runtime/assistant/` | `AssistantRequest`, `AssistantResponse`, `AssistantEngine`, `ToolCallRunner`, `AssistantContextAssembler`, `PermissionPolicy`, `AssistantHook`, `ConfirmationHook` (ADR 0025), and concrete assistant events. See `assistant.md`. |
| `shared/exceptions.py` | Generic exception hierarchy (`ZenithError` and a handful of domain-agnostic subclasses, including `EventBusError`) with no dependency on a specific runtime subsystem. |
| `shared/events/` | The event system: `Event`, `EventBus`, `EventLogger`. |
| `shared/utils/` | Small, reusable helpers (time, UUID, filesystem, text) with no dependency on `runtime/`. |
| `configs/config.py` | `Config` dataclass and TOML loader. |

`shared/` is kept free of anything specific to the Zenith assistant
runtime and is depended on by both applications in this repository —
the runtime and the Engineering Manager (`engineering_manager/`, see
`engineering_manager.md`). Neither application imports the other; see
ADR 0002.

## Import direction

Dependencies flow one way, from leaves to `Runtime`:

```
shared.exceptions, shared.utils
  -> shared.events (event -> event_logger -> bus)
    -> runtime.exceptions, state
      -> validation, configs.config
        -> registry, runtime.events.lifecycle_events
          -> commands (status -> validation -> command -> context, events -> executor)
          -> plugins (state -> validation -> manifest, plugin -> context, events -> registry)
          -> conversation (message, state -> validation -> conversation, events -> store)
          -> capabilities (tool, skill -> validation, catalog, events -> registries)
            -> providers (base -> registry, echo, scripted)
              -> assistant (status, request, response -> validation
                            -> permissions, hooks, assembler, tool_runner -> engine)
                -> context
                  -> console
                    -> runtime
```

`runtime/commands/context.py`, `runtime/commands/executor.py`,
`runtime/plugins/context.py`, `runtime/plugins/plugin.py`, and
`runtime/plugins/registry.py` all refer to `ApplicationContext` only in
`TYPE_CHECKING` blocks — `runtime.context` imports
`runtime.commands.executor` and `runtime.plugins.registry` at runtime
(for the `commands` and `plugins` fields), so a real import in the
other direction would be circular. `runtime/plugins/context.py` and
`runtime/plugins/plugin.py` similarly refer to
`runtime.plugins.registry.PluginRegistry` only under `TYPE_CHECKING`,
since `registry.py` imports `context.py` for real (to construct
`PluginContext`).

Every module under `runtime/conversation/`, `runtime/capabilities/`,
and `runtime/assistant/` that needs the `ApplicationContext` follows
the same rule, for the same reason: `runtime.context` imports
`ConversationStore` (the type) and `InMemoryConversationStore` (the
default factory — ADR 0018), both capability registries,
`AssistantProviderRegistry`, and `AssistantEngine` at runtime to build
its fields. `runtime/capabilities/skill.py` likewise refers to
`AssistantRequest` only under `TYPE_CHECKING`, since the assistant
package imports the capability package for real.

No module imports anything "above" it in this chain, so there are no
circular imports. `runtime/__init__.py` and `configs/__init__.py`
deliberately contain no imports, so importing a specific submodule never
requires the package's `__init__` to have finished executing first.
