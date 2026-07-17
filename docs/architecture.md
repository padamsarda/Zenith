# Runtime Architecture

This document describes the internal structure of the Zenith runtime as of
Milestone 4 (command execution framework). It covers what owns what, and
how control flows through startup and shutdown.

## Overview

```
main.py
  -> Runtime.run()
       -> Runtime.start()
       -> idle loop
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
6. `context.state = RUNNING`; emit `ApplicationStarted`.

## Shutdown sequence (`Runtime.stop`)

1. If already `STOPPED`, return (idempotent).
2. `context.state = STOPPING`; emit `ApplicationStopping`.
3. `context.state = STOPPED`; emit `ApplicationStopped`.

## Module map

| Module | Responsibility |
|---|---|
| `runtime/runtime.py` | Owns the lifecycle; the only module `main.py` depends on. |
| `runtime/context.py` | `ApplicationContext` dataclass. |
| `runtime/state.py` | `RuntimeState` enum. |
| `runtime/exceptions.py` | Exception hierarchy shared by every module. |
| `runtime/logging_setup.py` | Console logging configuration. |
| `runtime/registry.py` | `ServiceRegistry`. |
| `runtime/validation.py` | Guard functions used at system boundaries. |
| `runtime/events/` | `Event`, `EventBus`, `EventLogger`, and concrete lifecycle events. |
| `runtime/commands/` | `Command`, `CommandStatus`, `CommandResult`, `CommandContext`, `CommandExecutor`, and concrete command events. See `commands.md`. |
| `runtime/utils/` | Small, reusable helpers (time, UUID, filesystem, text). |
| `configs/config.py` | `Config` dataclass and TOML loader. |

## Import direction

Dependencies flow one way, from leaves to `Runtime`:

```
utils, exceptions, state
  -> validation, configs.config
    -> registry, events (event -> lifecycle_events, bus, event_logger)
      -> commands (status -> validation -> command -> context, events -> executor)
        -> context
          -> runtime
```

`runtime/commands/context.py` and `runtime/commands/executor.py` refer
to `ApplicationContext` only in `TYPE_CHECKING` blocks — `runtime.context`
imports `runtime.commands.executor` at runtime (for the `commands`
field), so a real import in the other direction would be circular.

No module imports anything "above" it in this chain, so there are no
circular imports. `runtime/__init__.py` and `configs/__init__.py`
deliberately contain no imports, so importing a specific submodule never
requires the package's `__init__` to have finished executing first.
