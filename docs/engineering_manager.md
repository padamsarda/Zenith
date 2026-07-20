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
  ├─ PlanCoordinator (orchestration/)    goal -> plan -> approved tasks
  ├─ Dispatcher (orchestration/)         task -> account -> session
  │    ├─ AssignmentPolicy               chooses the account
  │    └─ ContextAssembler               composes the session brief
  └─ ExecutionEngine (orchestration/)    the reconcile-and-advance tick
       └─ RetryPolicy                    decides if failed work reruns
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
| `Plan` | auto UUID | `DRAFT -> IN_PROGRESS -> COMPLETED`, `-> CANCELLED` (both terminal) |
| `Task` | auto UUID | see below |
| `Session` | auto UUID | `ACTIVE <-> INTERRUPTED`, ending `COMPLETED` / `FAILED` / `ABANDONED` |
| `ProviderAccount` | (`provider_id`, `account_id`) | none — declarative data |

### Plan (ADR 0009)

A plan is how a high-level goal becomes executable work: one goal,
stated once, decomposed into tasks that reference it via
`Task.plan_id` (standalone tasks remain first-class). `approve_plan`
is gate one in bulk — the plan moves to `IN_PROGRESS` and its DRAFT
tasks to `READY`; nothing in an unapproved plan is eligible for
dispatch. The plan completes itself when its last task reaches a
terminal status. Tasks may join an `IN_PROGRESS` plan as new work is
discovered, and `add_task_dependency` lets existing schedulable tasks
gain predecessors — guarded by an explicit cycle check
(`orchestration/graph.py`). The graph module also *derives* execution
structure on demand: `execution_waves` (what may run in parallel) and
`blockages` (what is blocked, or doomed by a cancelled dependency —
surfaced via `manager.blocked_tasks`).

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
modeled, not treated as failure. `resume_at` records when the execution
engine may resume an interrupted session automatically; `None` means a
human must (`AWAITING_INPUT` interruptions are never auto-resumed).
Sessions are mutated only through validated methods: `transition_to`,
`update_external_ref` (a resume may issue a fresh reference),
`set_resume_at`, and `close` (stamps `ended_at`/`summary` once
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
`engineering_tools/watchdog` used to do manually for Claude Code (now
automated by `ClaudeCodeProvider`, below). `ProviderSessionStatus` also
carries `usage: dict[str, Any] | None` — an additive field (ADR 0005
anticipated the contract growing this way) for provider-specific
accounting such as token counts and cost; `None` when a provider has
nothing to report.

`SessionSpec.metadata` is the provider-specific extension point, like
`Command.metadata`. Accounts are data, never classes; credentials are
never stored — each provider implementation resolves its own from the
account ID.

`InMemoryProvider` is the reference implementation and universal test
double. `ProviderRegistry` mirrors `ServiceRegistry`: explicit
`register`/`get`/`has`/`list`, no discovery, no magic.

### ClaudeCodeProvider

The first real provider (ADR 0014, `engineering_manager/providers/
claude_code.py`): runs `claude --print <instructions> --output-format
json` as one non-interactive subprocess per session, in the task's
project directory. `check_session` polls the subprocess rather than
blocking on it; a background thread continuously drains its combined
output so a long task cannot deadlock on a full pipe. A clean exit is
parsed as the CLI's own JSON result (`is_error` distinguishes an
application-level failure from a crash); a nonzero exit is scanned for
the same session-limit line `engineering_tools/watchdog` detects —
`SESSION_LIMIT_MARKER` and `parse_reset_time` are imported from it
rather than re-derived — reporting `LIMIT_REACHED` with the parsed
`resume_at`. `resume_session` starts a fresh `claude --continue`
subprocess in the same directory, exactly the recovery the watchdog
performs by hand.

Credentials resolve from the account ID via an environment-variable
convention (`ZENITH_CLAUDE_<ACCOUNT>_API_KEY`, normalized upper-case);
without one, the subprocess inherits the environment unchanged and
relies on however `claude` is already authenticated on the machine.
Session tracking is in-memory only — a restart loses it for any session
still running, which surfaces as an unknown-handle error the execution
engine already treats as lost work and recovers from via the retry
policy.

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
`ACTIVE` project, whose plan (if any) is `IN_PROGRESS`, with all
dependencies `DONE` — highest priority first, then oldest.

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

### The execution engine (ADR 0008)

`ExecutionEngine` (`orchestration/engine.py`) is what turns all of the
above from bookkeeping into autonomous execution. One synchronous,
deterministic `tick()` advances the whole system in a fixed order:

1. **Reconcile** every `ACTIVE` session against `check_session`:
   `FINISHED` → `complete_session` (the provider's `detail` becomes the
   session summary); `FAILED` → `fail_session`; `LIMIT_REACHED` →
   `interrupt_session` with a `resume_at` (the provider's, or now + a
   configured backoff); `AWAITING_INPUT` → interrupt with no
   `resume_at` plus an `AttentionRequired` event. A provider that
   *raises* has lost the session — it is failed and recovered like any
   other failure, which is the entire crash-recovery story: after a
   restart, the next tick reconciles persisted state against provider
   truth exactly like any other tick.
2. **Resume** every `INTERRUPTED` session whose `resume_at` has passed.
3. **Retry** every `FAILED` task the `RetryPolicy` approves
   (`orchestration/retry.py`; default `LimitedRetryPolicy`, three
   attempts, counted from the persisted session history — never
   stored). Exhausted tasks stay `FAILED` for a human, announced once
   via `AttentionRequired`.
4. **Dispatch** eligible tasks until none remain or accounts saturate.

`tick()` returns a frozen `TickReport` of everything that moved.
`run()` is only `tick()` on an interval with an injectable `sleep` —
every decision lives in the tick (ADR 0007). The engine holds no state
between ticks; parallelism is the dependency graph's width bounded by
free accounts, and "which provider does what" remains entirely the
`AssignmentPolicy`'s answer.

### Context between sessions (ADR 0010)

`ContextAssembler` (`orchestration/context.py`) composes each
dispatched session's instructions deterministically from durable state:
project, plan goal, task description, summaries of `DONE`
dependencies' completing sessions, and summaries of this task's failed
or abandoned attempts. Session summaries are the only interchange —
providers influence future context purely by summarizing well. Nothing
is stored, so the brief can never go stale and survives restarts by
construction.

## Events

Defined in `engineering_manager/events.py`, emitted with
`source="engineering_manager"`, persisted to the event log, and emitted
on the bus: `ProjectAdded`, `ProjectStatusChanged`, `PlanAdded`,
`PlanStatusChanged`, `TaskAdded`, `TaskDependencyAdded`,
`TaskStatusChanged`, `SessionStarted`, `SessionStatusChanged`,
`AttentionRequired`, `AccountAdded`, `AccountRemoved`. Status-change
events carry `from`/`to` in the payload; subscribers filter on payload
rather than having one event type per transition. `AttentionRequired`
is the engine's signal that only a human can move something forward
(payload `kind`: `session_awaiting_input` or `task_retries_exhausted`).

## CLI

```bash
python -m engineering_manager [--db PATH] <command>

python -m engineering_manager init
python -m engineering_manager project add zenith "Zenith" --path .
python -m engineering_manager plan add zenith "Ship plugin support"
python -m engineering_manager task add zenith "Implement the loader" --plan <plan-id> --priority 5
python -m engineering_manager task depend <task-id> <depends-on-id>
python -m engineering_manager plan approve <plan-id>
python -m engineering_manager plan show <plan-id>       # execution waves
python -m engineering_manager task approve <task-id>    # standalone tasks
python -m engineering_manager task list --status READY
python -m engineering_manager account add claude-code personal
python -m engineering_manager status
python -m engineering_manager log
python -m engineering_manager run --interval 30 --max-ticks 10
```

The database defaults to `~/.zenith/engineering_manager.db`. `run`
registers `ClaudeCodeProvider` (`--claude-command` overrides the
executable, default `claude`) and calls `manager.run()`; accounts must
already exist (`account add claude-code <id>`) for anything to actually
dispatch. Programmatic use, or wiring a different provider:

```python
from pathlib import Path
from engineering_manager.manager import EngineeringManager
from engineering_manager.store.store import Store

manager = EngineeringManager(Store(Path.home() / ".zenith" / "engineering_manager.db"))
manager.register_provider(my_provider)          # a Provider implementation
manager.add_account(my_provider.provider_id, "personal")
manager.run(interval_seconds=30.0)              # the autonomous loop
# ...or advance one deterministic step at a time:
report = manager.tick()
```

## Deliberate deferrals

Documented here so they read as decisions, not oversights (details in
`docs/roadmap.md`):

- **Real provider integrations** — shipped: `ClaudeCodeProvider` (ADR
  0014), generalizing the watchdog, and the CLI's `run` command it
  unblocked. A second real adapter (e.g. an HTTP-API provider) remains
  the next pressure test of the contract's provider-agnosticism.
- **AI-performed planning** — plans are the representation; a
  planning-provider session that writes a decomposition through the
  facade is future work needing no new mechanism.
- **Cross-call transactions** — each store method commits itself;
  fine while one process owns the database (ADR 0004).
- **Richer completion reports** — context assembly (ADR 0010) reads
  session summaries; if summaries prove too thin, sessions gain a
  structured completion report feeding the same assembler.
