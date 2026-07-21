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
  ├─ PlanningSessionRunner (orchestration/) goal -> AI-decomposed DRAFT plan
  ├─ Dispatcher (orchestration/)         task -> account -> session
  │    ├─ AssignmentPolicy               chooses the account
  │    └─ ContextAssembler               composes the session brief
  ├─ ExecutionEngine (orchestration/)    the reconcile-and-advance tick
  │    ├─ RetryPolicy                    decides if failed work reruns
  │    └─ VerificationPolicy             checks a claimed completion before trusting it
  └─ report.py (orchestration/)          durable state -> a Markdown status report
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

A plan's tasks need not be decomposed by hand: `manager.plan_from_goal`
(ADR 0020) asks a registered `Provider` to break the goal into tasks and
dependencies, then writes the result through the ordinary `add_plan`/
`add_task`/`add_task_dependency` path — the plan lands in `DRAFT`,
exactly as reviewable as one a human wrote, since `approve_plan` is
still the only gate to dispatch. See "AI-performed planning" below.

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

## AI-performed planning (ADR 0020)

`manager.plan_from_goal(project_id, goal, provider_id=..., account_id=...,
description=None, model=None)` turns a goal into a reviewable plan with
no human decomposing it by hand:

```python
plan = manager.plan_from_goal(
    "zenith", "Ship plugin support", provider_id="claude-code", account_id="personal"
)
# plan is DRAFT, its tasks are DRAFT — review, then:
manager.approve_plan(plan.plan_id)
```

1. Records the goal as a `DRAFT` plan immediately (`add_plan`), so even
   a failed attempt below leaves an auditable trace.
2. `PlanningSessionRunner` (`orchestration/planning.py`) runs one
   bounded, synchronous session through the *same* `Provider` contract
   (ADR 0005) real engineering work uses, asking it to respond with a
   JSON task array — polling itself to completion rather than being
   driven by `ExecutionEngine`'s ticks, since a caller is actively
   waiting on it. A `LIMIT_REACHED`/`AWAITING_INPUT`/`FAILED` report, or
   a timeout, raises `OrchestrationError`; the empty `DRAFT` plan stays
   behind either way.
3. `parse_decomposition` (`orchestration/planning_decomposition.py`)
   tolerantly extracts a JSON array from the output (markdown fences and
   surrounding prose are stripped) into `TaskDraft`s; an item missing a
   usable title is skipped rather than failing the whole decomposition.
4. Each draft becomes a task via the ordinary `add_task`; each
   `depends_on` index becomes an edge via the ordinary
   `add_task_dependency` — a would-be cycle or bad index is logged and
   skipped, not raised, since the plan is reviewed before it can run
   regardless. Publishes `PlanDecomposed` on success.

`approve_plan` remains the only gate to dispatch (ADR 0009) — an
AI-authored decomposition is exactly as safe to accept into the store as
a human-authored one, because nothing in it can execute unreviewed.

The CLI: `plan from-goal <project_id> "<goal>" --account <id> [--provider claude-code] [--model ...] [--timeout-seconds 600]`.

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
session per account and picks the first free one. `ConcurrencyLimitedPolicy`
generalizes that to a configurable cap per `provider_id` — counted
across every account on that provider, since some providers can
genuinely run several sessions at once and others exactly one. Further
policies (cost, capability, past performance) replace either class
without touching the dispatcher.

`VerificationPolicy` (`orchestration/verification.py`, ADR 0019) is the
seam for "should this claimed completion be trusted?", consulted by the
execution engine — see below — not the dispatcher. `NoVerificationPolicy`
is the default (trusts every provider). `CommandVerificationPolicy` runs
a command (default `python -m pytest`) in the task's project directory,
synchronously, with a timeout; a nonzero exit or a timeout fails
verification, with captured output as the detail. Configure it with
`manager.set_verification_policy(...)`.

### The execution engine (ADR 0008)

`ExecutionEngine` (`orchestration/engine.py`) is what turns all of the
above from bookkeeping into autonomous execution. One synchronous,
deterministic `tick()` advances the whole system in a fixed order:

1. **Reconcile** every `ACTIVE` session against `check_session`:
   `FINISHED` → checked against the configured `VerificationPolicy`
   (ADR 0019) before being trusted: a pass calls `complete_session` (the
   provider's `detail` becomes the session summary) exactly as before; a
   failure calls `fail_session` instead, with the policy's own detail as
   the reason — an ordinary recoverable failure the retry phase below
   re-evaluates like any other, not a new outcome. The default
   `NoVerificationPolicy` always passes, so this is a no-op unless a
   policy is configured (`manager.set_verification_policy`, or the CLI's
   `run --verify-command`). `FAILED` → `fail_session`; `LIMIT_REACHED` →
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
   stored). `ExponentialBackoffRetryPolicy` adds failure-aware backoff
   on top of the same attempt budget: it declines a retry, not just
   once attempts run out, but also until `base_delay * multiplier **
   (attempt - 1)` has elapsed since the most recent failure — no engine
   change needed, since `tick()` already re-evaluates every `FAILED`
   task on every interval, which is exactly what backoff needs. (Its
   `clock` must agree with real session timestamps unless the `Session`
   objects it is given were built to match a scripted one — `Dispatcher`
   always stamps `ended_at` with the real clock, not the engine's own
   injectable one.) Exhausted tasks stay `FAILED` for a human, announced
   once via `AttentionRequired`.
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

## Engineering reports

`manager.project_report(project_id)` renders a Markdown status report —
plans, a task-status breakdown, work in `NEEDS_REVIEW` with its
completing session's summary, blocked tasks (`orchestration/graph.py`'s
`blockages`), recent `AttentionRequired` entries for the project's own
tasks, and a session-outcome summary — composed by `build_report`
(`orchestration/report.py`) deterministically from durable state alone,
the same principle `ContextAssembler` applies to session briefs. This is
the "what happened while I was away" a human needs after leaving the
engine running unattended; nothing here is stored, so the report is
always current. CLI: `project report <project_id> [--out PATH]`.

## Events

Defined in `engineering_manager/events.py`, emitted with
`source="engineering_manager"`, persisted to the event log, and emitted
on the bus: `ProjectAdded`, `ProjectStatusChanged`, `PlanAdded`,
`PlanDecomposed`, `PlanStatusChanged`, `TaskAdded`, `TaskDependencyAdded`,
`TaskStatusChanged`, `SessionStarted`, `SessionStatusChanged`,
`AttentionRequired`, `AccountAdded`, `AccountRemoved`. Status-change
events carry `from`/`to` in the payload; subscribers filter on payload
rather than having one event type per transition. `AttentionRequired`
is the engine's signal that only a human can move something forward
(payload `kind`: `session_awaiting_input` or `task_retries_exhausted`).
`PlanDecomposed` (payload: `plan_id`, `project_id`, `task_count`) marks
a successful `plan_from_goal` (ADR 0020).

## CLI

```bash
python -m engineering_manager [--db PATH] <command>

python -m engineering_manager init
python -m engineering_manager project add zenith "Zenith" --path .
python -m engineering_manager plan add zenith "Ship plugin support"
python -m engineering_manager plan from-goal zenith "Ship plugin support" --account personal
python -m engineering_manager task add zenith "Implement the loader" --plan <plan-id> --priority 5
python -m engineering_manager task depend <task-id> <depends-on-id>
python -m engineering_manager plan approve <plan-id>
python -m engineering_manager plan show <plan-id>       # execution waves
python -m engineering_manager task approve <task-id>    # standalone tasks
python -m engineering_manager task list --status READY
python -m engineering_manager account add claude-code personal
python -m engineering_manager status
python -m engineering_manager project report zenith --out report.md
python -m engineering_manager log
python -m engineering_manager run --interval 30 --max-ticks 10 --verify-command "python -m pytest"
```

The database defaults to `~/.zenith/engineering_manager.db`. `run`
registers `ClaudeCodeProvider` (`--claude-command` overrides the
executable, default `claude`) and calls `manager.run()`; accounts must
already exist (`account add claude-code <id>`) for anything to actually
dispatch. `--verify-command` configures a `CommandVerificationPolicy`
(ADR 0019) so a claimed completion is checked before `NEEDS_REVIEW`,
rather than trusted outright — the recommended setting for anything left
running unattended. `plan from-goal` registers `ClaudeCodeProvider` the
same way and asks it to decompose the goal (ADR 0020); `--provider`
names a different registered provider instead. Programmatic use, or
wiring a different provider:

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
- **AI-performed planning** — shipped: `manager.plan_from_goal` (ADR
  0020) runs a planning-provider session and writes the decomposition
  through the facade, exactly as anticipated, needing no new mechanism.
- **A verification gate before NEEDS_REVIEW** — shipped:
  `VerificationPolicy` (ADR 0019), consulted by the execution engine
  when a provider reports `FINISHED`; a failure is folded into the
  existing retry loop via `fail_session`, not a new outcome kind.
- **Engineering reports** — shipped: `manager.project_report` composes
  a Markdown status report from durable state alone
  (`orchestration/report.py`); no new storage, since everything it reads
  already exists.
- **Cross-call transactions** — each store method commits itself;
  fine while one process owns the database (ADR 0004).
- **Richer completion reports** — context assembly (ADR 0010) reads
  session summaries; if summaries prove too thin, sessions gain a
  structured completion report feeding the same assembler.
