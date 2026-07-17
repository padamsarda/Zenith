# Command Execution Framework

The structured, auditable path through which Zenith performs actions.
Every future capability — opening an application, sending an email,
calling a plugin — executes through this framework rather than being
invoked directly, so every action is validated, timed, logged, and
announced on the `EventBus` the same way.

## Overview

```
Command            what to do (immutable data)
CommandContext     what a running command can see (ApplicationContext + execution metadata)
CommandExecutor     runs a Command's action and produces a CommandResult
CommandResult       what happened
```

The framework is deliberately inert on its own: `Command` carries no
behavior, and `CommandExecutor` carries no knowledge of what any
particular command does. Behavior is supplied by the caller as an
`action` callable at the point of execution — the executor only knows
how to run one safely.

## Command

`runtime.commands.command.Command` (frozen dataclass) is a structured
description of a single action:

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Required. What the command is. |
| `description` | `str \| None` | Optional human-readable detail. |
| `metadata` | `dict[str, Any]` | Optional extra data. Defaults to `{}`. |
| `command_id` | `UUID` | Unique per command, auto-generated. |
| `created_at` | `datetime` | UTC, auto-generated. |
| `status` | `CommandStatus` | Defaults to `CREATED`. |

Every field is fixed at creation except `status`. `status` cannot be
assigned directly (`command.status = x` raises `FrozenInstanceError`,
same as any other field on a frozen dataclass) — it can only be moved
forward through `command.transition_to(new_status)`, which validates the
transition first. Constructing a `Command` does not itself validate
`name` or `metadata`; that happens at the framework boundary (see
Validation below), mirroring how `configs.config.Config` is validated
separately from construction.

## CommandStatus

`runtime.commands.status.CommandStatus` is an enum:

```
CREATED -> QUEUED -> RUNNING -> COMPLETED
       \-----------> RUNNING -> FAILED
                              -> CANCELLED
```

`COMPLETED`, `FAILED`, and `CANCELLED` are terminal — no further
transition is valid from any of them (`runtime.commands.status.TERMINAL_STATUSES`).
`QUEUED` is reserved for a future queuing system; nothing in this
milestone enters it — `CommandExecutor` moves a command directly from
`CREATED` to `RUNNING`.

## CommandResult

`runtime.commands.result.CommandResult` (frozen dataclass) is what
`CommandExecutor.execute` always returns — never `None`:

| Field | Type | Description |
|---|---|---|
| `success` | `bool` | Whether the command completed without failing or being cancelled. |
| `message` | `str` | Human-readable outcome summary. |
| `duration_seconds` | `float` | Wall-clock execution time, measured with `time.perf_counter()` (monotonic — immune to system clock changes). |
| `data` | `Any` | The action's return value, if any. |
| `exception` | `BaseException \| None` | The exception raised by validation or the action, if any. |

## CommandContext

`runtime.commands.context.CommandContext` (frozen dataclass) is built
fresh by `CommandExecutor` for each `execute` call and passed to the
action:

| Field | Type | Description |
|---|---|---|
| `application_context` | `ApplicationContext` | The shared runtime context — gives the action access to `services`, `events`, `config`, etc. |
| `command_id` | `UUID` | The executing command's ID. |
| `started_at` | `datetime` | UTC, set when the context is built. |
| `cancellation_token` | `CancellationToken` | Placeholder — see below. |
| `metadata` | `dict[str, Any]` | Execution-scoped extra data, separate from `Command.metadata`. |

`CancellationToken` (also in `context.py`) is a placeholder for future
cooperative cancellation: it carries a `cancelled: bool = False` field
that nothing in this milestone ever sets. It exists so `CommandContext`
has a stable place to check for cancellation once a real mechanism is
built, without a breaking change later.

## CommandExecutor

`runtime.commands.executor.CommandExecutor` is the only thing that runs
a `Command`.

```python
result = executor.execute(command, application_context, action)
```

`action` is any `Callable[[CommandContext], Any]` — the actual work.
The executor knows nothing about what it does; it only runs it inside a
validated, timed, logged, event-emitting harness. This is why the
executor "does not know about plugins": a future plugin system supplies
`action`, the executor just runs it the same way it would run anything
else.

### Execution flow

1. Emit `CommandCreated`.
2. `validate(command)` — structural checks plus a duplicate-ID check
   (see Validation). On failure: mark `FAILED` (unless already
   terminal), log, emit `CommandFailed`, return a failed `CommandResult`.
3. Record the command's ID as executed, transition to `RUNNING`, emit
   `CommandStarted`, log.
4. Build a `CommandContext` and call `action(context)`.
   - Raises `CommandCancelledError`: transition to `CANCELLED`, log,
     emit `CommandCancelled`, return a failed `CommandResult`.
   - Raises anything else: transition to `FAILED`, log, emit
     `CommandFailed`, return a failed `CommandResult`.
   - Returns normally: transition to `COMPLETED`, log, emit
     `CommandCompleted`, return a successful `CommandResult` carrying
     the return value as `data`.

`execute` never raises because of validation or the action — every
outcome becomes a `CommandResult`.

### Validation

`validate(command)` (also callable standalone, not just from `execute`)
raises `CommandValidationError` if:

- `command.name` is empty, whitespace-only, or padded with whitespace
  (`runtime.commands.validation.validate_command_name`).
- `command.metadata` is not a `dict`, or has a non-`str` key
  (`validate_command_metadata`).
- `command.command_id` has already been executed by this
  `CommandExecutor` instance — each executor tracks executed IDs in
  memory for its own lifetime; this is not a persistent or shared
  store.

Status transitions are validated separately, inside
`Command.transition_to`, against
`runtime.commands.validation.validate_status_transition` — an invalid
transition (e.g. `COMPLETED -> RUNNING`) raises `CommandValidationError`
immediately rather than silently succeeding.

## Command events

Defined in `runtime.commands.events`, all `Event` subclasses emitted by
`CommandExecutor` with `source="command_executor"`:

- `CommandCreated` — payload: `command_id`, `name`.
- `CommandStarted` — payload: `command_id`, `name`.
- `CommandCompleted` — payload: `command_id`, `duration_seconds`.
- `CommandFailed` — payload: `command_id`, `reason`.
- `CommandCancelled` — payload: `command_id`, `reason`.

These follow the same rules as every other event on the bus (see
`events.md`): type-exact dispatch, subscription order preserved, a
failing listener is logged and does not stop the others.

## Exceptions

Added to `runtime.exceptions`, all under `CommandError(ZenithError)`:

- `CommandValidationError` — validation or transition failure.
- `CommandExecutionError` — available for an `action` to raise to
  report a structured failure; the executor treats it like any other
  exception from `action` (caught, logged, turned into a failed
  `CommandResult`).
- `CommandCancelledError` — raised by an `action` to signal cooperative
  cancellation; the executor treats this distinctly from a generic
  failure (`CANCELLED` status and `CommandCancelled`, not `FAILED` and
  `CommandFailed`).

## Interaction with Runtime and ApplicationContext

`ApplicationContext` owns one `CommandExecutor` (`context.commands`),
created the same way it owns `services` and `events` — a
`field(default_factory=CommandExecutor)`. `Runtime` itself does not call
`context.commands.execute` anywhere in this milestone; the lifecycle it
owns (`start` / `stop`) has no commands to run yet. What this milestone
establishes is the path every future capability will use:

```
Runtime -> ApplicationContext.commands (CommandExecutor)
             .execute(command, application_context, action)
               -> emits CommandCreated/Started/Completed|Failed|Cancelled
                  on ApplicationContext.events
```

Anything that wants to react to command execution — logging, future UI,
future plugins — subscribes to these events on `context.events`, exactly
as it would for the existing lifecycle events.
