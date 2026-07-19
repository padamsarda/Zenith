# Engineering Manager

The Engineering Manager (`engineering_manager/`) is the second
application in this repository: a local-first platform for coordinating
AI-performed engineering work across projects, providers, and accounts.
It is fully independent of the Zenith assistant runtime — it imports
only `shared/` and the standard library (ADR 0002) — and Zenith itself
is intended to eventually become just one of its managed projects.

The problem it removes: today the human decides which AI performs each
task, tracks state between sessions, resumes interrupted work, and
remembers why decisions were made. The Engineering Manager makes those
mechanical parts persistent and automatic while keeping the human in
charge of two things only: approving what should be done, and accepting
what was done.

## Overview

```
EngineeringManager (manager.py)          the facade every interface uses
  ├─ Store (store/)                      SQLite persistence + event log
  ├─ ProviderRegistry (providers/)       available Provider integrations
  ├─ EventBus (shared/events)            live in-process notifications
  └─ Dispatcher (orchestration/)         task -> account -> session
       └─ AssignmentPolicy               chooses the account
```

Domain objects (`domain/`) follow the same patterns as the runtime's
`Command` and `Plugin`: frozen dataclasses, unvalidated at construction,
validated at framework boundaries by guard functions, with lifecycle
state that only moves through `transition_to` against an explicit
transition table.

## Domain model

| Entity | Identity | Lifecycle |
|---|---|---|
| `Project` | author-chosen slug (`project_id`) | `ACTIVE <-> PAUSED`, `-> ARCHIVED` (terminal) |
| `Task` | auto UUID | see below |
| `Session` | auto UUID | `ACTIVE <-> INTERRUPTED`, ending `COMPLETED` / `FAILED` / `ABANDONED` |
| `ProviderAccount` | (`provider_id`, `account_id`) | none — declarative data |

### Task lifecycle (ADR 0006)

```
DRAFT -> READY -> IN_PROGRESS -> NEEDS_REVIEW -> DONE
            ^          |               |
            |          +-> FAILED -----+-> READY (retry / rework)
            |          +-> READY (abandoned session)
            +--- DRAFT (revise)        any non-terminal -> CANCELLED
```

Two transitions are **human approval gates**, exposed as explicit
facade methods:

- `approve_task` — `DRAFT -> READY`: "yes, do this."
- `accept_task` — `NEEDS_REVIEW -> DONE`: "yes, the work is good."

`IN_PROGRESS -> DONE` does not exist; nothing completes without review.
`DONE` and `CANCELLED` are the only terminal statuses — failure is
always recoverable (`retry_task`, `rework_task`).

Tasks carry `priority` (higher dispatches first) and `depends_on` (task
IDs that must be `DONE` before it may dispatch). Dependencies must
already exist in the same project when a task is created, which makes
cycles impossible by construction.

### Session

A `Session` is one continuous stretch of provider work on one task. Its
`external_ref` is the opaque provider-side reference (conversation ID,
process handle, …) that makes an `INTERRUPTED` session resumable rather
than restartable — interruption is expected (session limits), so it is
modeled, not treated as failure. Sessions are mutated only through
validated methods: `transition_to`, `update_external_ref` (a resume may
issue a fresh reference), and `close` (stamps `ended_at`/`summary` once
terminal).

## Provider abstraction (ADR 0005)

`providers/base.py` defines the entire vocabulary orchestration speaks
to any AI provider:

```python
handle = provider.start_session(spec)     # SessionSpec -> SessionHandle
status = provider.check_session(handle)   # -> ProviderSessionStatus
handle = provider.resume_session(handle)  # may return a fresh handle
provider.stop_session(handle)
```

`ProviderSessionState` is `RUNNING`, `AWAITING_INPUT`, `LIMIT_REACHED`,
`FINISHED`, or `FAILED`. `LIMIT_REACHED` (with optional `resume_at`) is
deliberately first-class: it is the one interruption the orchestrator
recovers from automatically, generalizing what
`engineering_tools/watchdog` does manually for Claude Code today.

`SessionSpec.metadata` is the provider-specific extension point, like
`Command.metadata`. Accounts are data, never classes; credentials are
never stored — each provider implementation resolves its own from the
account ID.

`InMemoryProvider` is the reference implementation and universal test
double. `ProviderRegistry` mirrors `ServiceRegistry`: explicit
`register`/`get`/`has`/`list`, no discovery, no magic.

## Persistence (ADR 0004)

`store/` is stdlib `sqlite3` behind one `Store` class:

- `database.py` — connection setup (WAL, foreign keys) and append-only
  `MIGRATIONS` applied via SQLite's `user_version`. Old databases
  upgrade on open; databases newer than the code are refused loudly.
- `serialization.py` — explicit entity <-> row conversion. Enums by
  `.name`, datetimes as ISO-8601, UUIDs as strings, dependencies as a
  sorted JSON array.
- `store.py` — strict CRUD: `add_*` raises `DuplicateEntityError` on
  collision, `update_*` raises `*NotFoundError` on absence. Never an
  upsert.

The `event_log` table is an append-only audit trail. Every event the
facade or dispatcher emits is written here **and** emitted on the
`EventBus`: the log serves history ("what happened while I was away"),
the bus serves live subscribers. State tables remain the source of
truth — this is not event sourcing.

## Orchestration

`Dispatcher.eligible_tasks()` returns tasks that are `READY`, in an
`ACTIVE` project, with all dependencies `DONE` — highest priority
first, then oldest.

`Dispatcher.dispatch()`:

1. Pick the task (highest-priority eligible, or the one named).
2. Collect accounts whose provider is registered; none at all is a
   configuration error (`OrchestrationError`).
3. Ask the `AssignmentPolicy` to choose an account, given the open
   (ACTIVE or INTERRUPTED) sessions. No free account: return `None`
   (or raise, if a specific task was named).
4. `provider.start_session(spec)` — on provider failure nothing is
   persisted and the task stays `READY`.
5. Persist the `Session`, move the task to `IN_PROGRESS`, publish
   `SessionStarted` and `TaskStatusChanged`.

Session lifecycle methods keep task and session in lockstep:

| Method | Session | Task |
|---|---|---|
| `complete_session` | `COMPLETED` (closed) | `-> NEEDS_REVIEW` |
| `fail_session` | `FAILED` (closed) | `-> FAILED` |
| `interrupt_session` | `-> INTERRUPTED` | stays `IN_PROGRESS` |
| `resume_session` | `-> ACTIVE`, new `external_ref` | stays `IN_PROGRESS` |
| `abandon_session` | `ABANDONED` (closed, provider stop attempted) | `-> READY` |

`AssignmentPolicy` (`orchestration/policy.py`) is the seam for "which
AI should do this?". The default `FirstAvailablePolicy` allows one open
session per account and picks the first free one; smarter policies
(cost, capability, past performance) replace the class without touching
the dispatcher.

## Events

Defined in `engineering_manager/events.py`, emitted with
`source="engineering_manager"`, persisted to the event log, and emitted
on the bus: `ProjectAdded`, `ProjectStatusChanged`, `TaskAdded`,
`TaskStatusChanged`, `SessionStarted`, `SessionStatusChanged`,
`AccountAdded`, `AccountRemoved`. Status-change events carry
`from`/`to` in the payload; subscribers filter on payload rather than
having one event type per transition.

## CLI

```bash
python -m engineering_manager [--db PATH] <command>

python -m engineering_manager init
python -m engineering_manager project add zenith "Zenith" --path .
python -m engineering_manager task add zenith "Implement the loader" --priority 5
python -m engineering_manager task approve <task-id>
python -m engineering_manager task list --status READY
python -m engineering_manager account add claude personal
python -m engineering_manager status
python -m engineering_manager log
```

The database defaults to `~/.zenith/engineering_manager.db`. Dispatch
is not exposed in the CLI yet: it requires a registered `Provider`, and
real provider integrations are the top roadmap item. Programmatic use:

```python
from pathlib import Path
from engineering_manager.manager import EngineeringManager
from engineering_manager.store.store import Store

manager = EngineeringManager(Store(Path.home() / ".zenith" / "engineering_manager.db"))
manager.register_provider(my_provider)          # a Provider implementation
manager.add_account(my_provider.provider_id, "personal")
session = manager.dispatch()                    # highest-priority READY task
```

## Deliberate deferrals

Documented here so they read as decisions, not oversights (details in
`docs/roadmap.md`):

- **Real provider integrations** — the contract is proven against
  `InMemoryProvider`; the first real adapter (Claude Code CLI,
  generalizing the watchdog) is roadmap item one.
- **The autonomous scheduler loop** — a long-running process that polls
  `check_session`, resumes on `LIMIT_REACHED`, and dispatches as
  accounts free up. All of its building blocks exist and are tested.
- **Cross-call transactions** — each store method commits itself;
  fine while one process owns the database (ADR 0004).
- **Context/knowledge handoff between sessions** — what a session
  learned lives only in `summary` for now; structured context transfer
  is a designed-for but unbuilt layer.
