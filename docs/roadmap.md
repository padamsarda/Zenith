# Roadmap

Where this repository is headed, in dependency order. Each item builds
on what exists; none requires reworking current foundations. This file
is direction, not commitment — reorder freely, but record significant
design choices as ADRs (`architecture/`) when implementing.

**Product direction (2026-07-21):** the runtime being built here is
**Zeni**, a personal assistant meant to be used every day — not just an
engineering tool. The Engineering Manager remains infrastructure Zeni
can use internally, not the product. Priorities below are now judged
against "does this make Zeni more useful tomorrow": vertical slices a
person actually invokes (opening an app, controlling media, eventually
voice and memory) outrank engineering-only capability unless the two
overlap. Credential-gated integrations (Spotify's own API, Notion,
GitHub, WhatsApp, Calendar, email, voice STT/TTS) are deliberately
deferred to whenever real credentials and product decisions are
available to wire them — see the "Zenith runtime" section below for
what is buildable without them right now.

## Engineering Manager

The execution engine — plans, the evolving task graph, the
reconcile-and-advance tick, retry policies, and deterministic context
assembly — shipped in ADRs 0008–0010. What remains is attaching real
providers and hardening around them; orchestration itself should not
need redesign.

### 1. First real provider adapter (highest value) — shipped

`ClaudeCodeProvider` (`engineering_manager/providers/claude_code.py`,
ADR 0014) drives Claude Code as a subprocess, generalizing
`engineering_tools/watchdog`: starts a session in a project's working
directory (`start_session`), detects completion and session limits
(`check_session` reporting `LIMIT_REACHED` with `resume_at`, reusing the
watchdog's proven parsing rather than rewriting it), resumes with
`--continue` (`resume_session`), terminates (`stop_session`). `run` is
now exposed in the CLI. A second adapter (e.g. an HTTP-API provider)
remains the next pressure test of the contract's provider-agnosticism;
extend `Provider`/`SessionSpec` additively if it falls short (ADR 0005).

### 2. AI-performed planning — shipped

`manager.plan_from_goal` (ADR 0020) runs a planning session through the
existing `Provider` contract — `PlanningSessionRunner`
(`orchestration/planning.py`) drives it to completion synchronously and
bounded, `parse_decomposition` (`orchestration/planning_decomposition.py`)
tolerantly turns the output into task drafts — and writes the result
through `add_plan`/`add_task`/`add_task_dependency`, exactly the "no new
mechanism" this item anticipated. Decompositions are reviewed exactly as
anticipated too: the plan lands in `DRAFT`, and `approve_plan` remains
the only gate to dispatch.

### 3. Richer assignment and retry policies — partially shipped

`ConcurrencyLimitedPolicy` (`orchestration/policy.py`) generalizes
`FirstAvailablePolicy`'s "one open session per account" to a
configurable cap per provider, counted across every account on it.
`ExponentialBackoffRetryPolicy` (`orchestration/retry.py`) adds
failure-aware delay on top of `LimitedRetryPolicy`'s attempt budget,
using nothing but the existing tick's polling to re-evaluate the delay
— no engine or dispatcher change, as this item anticipated. Both were
added, tested (including against a live `Dispatcher`/`ExecutionEngine`,
not just in isolation — see `ExponentialBackoffRetryPolicy`'s docstring
for a clock-consistency caveat that surfaced doing so), and documented
without touching either seam's shape.

Still open: cost/capability-aware assignment and model/task matching
(`SessionSpec.model` is already plumbed, but no `ProviderAccount` field
yet describes what a given account supports — this needs a concrete
domain field, not just a policy, so it's deferred rather than
half-built) and past-outcome-aware assignment (the event log already
records enough to build one). Both seams still absorb this without
engine or dispatcher changes.

### 4. Store hardening as concurrency arrives

When the engine loop and CLI can write concurrently: a unit-of-work
(one transaction spanning dispatch's task update + session insert),
`busy_timeout`, and possibly a join table for dependencies if SQL-side
queries become useful (ADR 0004 anticipates all three).

### 5. Zenith as a managed project — shipped

Done, and it earned its place at the top of this list. A `zenith`
project was registered, a real `ClaudeCodeProvider` planning session
decomposed a goal into a five-task dependency graph, and dispatched
sessions built the feature — verified by `python -m pytest` between
tasks, accepted at gate two, reported at the end. The mechanism needed
no redesign, exactly as predicted.

What it found was not orchestration bugs. It was that the *provider
boundary* had never been exercised against real work:

1. **Sessions could not act, and said they had.** `claude --print` runs
   with no stdin, so every edit was denied; the process still exited 0
   with `is_error: false`, which the adapter reported as `FINISHED`. Six
   sessions were recorded as successful completions of an untouched
   repository. ADR 0022 fixes both halves — denials fail loudly,
   `--permission-mode` grants authority explicitly.
2. **`acceptEdits` is a trap.** It permits file edits but not commands,
   and engineering means running the test suite. Unattended runs need
   `bypassPermissions`; `docs/workflow.md` now says so with a table
   instead of leaving it to be discovered over six failed sessions.
3. **Gate one was unreviewable.** `plan show` printed titles, and no
   `task show` existed — so approving a decomposition meant consenting
   to text the CLI would not display. Fixed with `plan show --detail`
   and `task show`.
4. **`plan from-goal --account X` left X unregistered**, reproducing the
   exact idle-forever failure ADR 0021 removed from `workflow`. It now
   registers the account, and `run` refuses to start when no account
   could ever dispatch.
5. **A project could not be relocated**, so aiming one at a disposable
   git worktree — the sane way to contain `bypassPermissions` — meant
   recreating it and abandoning its history. `project relocate` fixes
   it.
6. **A long session narrated nothing.** ADR 0021 taught `run` to log
   what each tick moved, but a tick spanning a ten-minute session moves
   nothing, so the terminal was silent and indistinguishable from a
   hang. `TickReport.sessions_running` gives the loop a liveness line.
7. **A failed run did not say why.** The report listed FAILED counts and
   "retries exhausted" without the reason any of it happened, sending a
   human back to the logs the report exists to replace. It now has a
   Failed Work section carrying each task's last failure reason.

Still open, and discovered here: **a deterministic failure still burns
the whole retry budget.** A permission denial cannot succeed on retry,
yet the policy spent three attempts per task proving it — six paid
sessions. The `RetryPolicy` seam can express this, but doing it honestly
needs the provider to *say* a failure is non-retryable rather than the
policy sniffing summary text, which means a field on
`ProviderSessionStatus` and one on `Session` to persist it. That is a
concrete domain change, not just a policy, so it is deferred rather than
half-built — the same reasoning applied to capability-aware assignment
in item 3.

### 6. A verification gate before NEEDS_REVIEW — shipped

Not originally on this list, but the obstacle it removes was the
sharpest one to the "walk away for hours" mission: nothing checked a
provider's `FINISHED` claim before trusting it. `VerificationPolicy`
(`orchestration/verification.py`, ADR 0019) closes that — the default
`NoVerificationPolicy` changes nothing; `CommandVerificationPolicy` runs
a command (a test suite, a linter) before a completion reaches
`NEEDS_REVIEW`, and a failure re-enters the existing retry loop rather
than becoming a new outcome kind. `run --verify-command` wires it from
the CLI.

### 7. Engineering reports — shipped

Also not originally on this list: after a long unattended run, nothing
composed "what happened" into something a human reads once, start to
finish — only the CLI's `status`/`log`, or subscribing to the bus.
`manager.project_report` (`orchestration/report.py`) renders a Markdown
report from durable state (plans, task breakdown, completed work,
work needing review, blockages, recent attention, session outcomes);
`project report <id> [--out PATH]` in the CLI, and written
automatically at the end of every `workflow` run.

### 8. One coherent lifecycle, not a collection of commands — shipped

Every step existed; the journey between them did not. Walking the
documented quickstart exactly as written showed it could not be
completed by anyone: `account add` was an undocumented prerequisite,
`run` never returned (its only bound counted loop iterations, not
work) and printed nothing, and gate two had no bulk form, so a plan
could never reach `COMPLETED`.

ADR 0021 closes this by composition, not new machinery.
`StopCondition` (`orchestration/stop.py`) gives `run` a termination
policy shaped like the existing seams — `RunForever` keeps the old
behavior, `WhenQuiescent`/`WhenPlanSettled` stop once nothing can
advance without a human — and `run` now returns a `RunReport` that
distinguishes settled from exhausted from interrupted. `accept_plan`
supplies the bulk gate two that mirrors `approve_plan`. `workflow`
(`cli_workflow.py`) calls the existing facade methods in the order the
lifecycle already implied, pausing at both gates.

Running it end to end is what found the one genuinely structural
problem: gate two is what makes a task `DONE`, and dependents are not
eligible until it is, so "execute to quiescence, then accept" stalls
every plan deeper than one wave. The fix was where the gate happens,
not whether — the workflow alternates execution with acceptance, and
the engine still cannot accept its own work.

`InMemoryProvider(finish_after_checks=...)` makes the whole lifecycle
runnable with no external process, so the documented workflow
(`docs/workflow.md`) is something a new contributor can actually
execute, and so it is covered end to end by
`tests/test_em_cli_workflow.py`.

Still open: nothing yet writes engineering artifacts *other than* the
report — a diff, a changelog entry, or a per-task record of what
changed would make the trail richer, and the session summaries needed
for it are already durable. Progress is reported per round rather than
live during a long tick, which is fine for a 30-second interval and
would not be for a 30-minute one.

## Zenith runtime

The assistant runtime — conversations, capabilities, the provider
contract, and the request pipeline — shipped in ADRs 0011–0013. The
foundation is in place: new capabilities, providers, and interfaces
plug in without redesign (`docs/assistant.md`). What remains is filling
it in.

### 1. First real assistant provider (highest value) — shipped

`ClaudeProvider` (`runtime/providers/claude.py`, ADR 0015) calls the
Claude Messages API directly over `urllib` (standard library only).
`generate_turn` maps `TurnBrief` to `AssistantTurn`: history to Claude's
message format (`claude_messages.py`), the `CapabilityCatalog` to its
tool schema, its response back to text and `ToolCall`s — including a
`ToolCallCache` that reconstructs `tool_use`/`tool_result` pairs across
turns with no engine change. `ToolParameter` gained the real type
vocabulary (JSON Schema) the previous version of this item asked
whether it would need — it did, and `type: str = "string"` answers it,
additively. A second adapter remains the next pressure test of the
contract's provider-agnosticism; extend it additively if it falls short
(ADR 0011).

### 2. Durable conversations — shipped

`ConversationStore` is now an ABC (ADR 0018); `InMemoryConversationStore`
is the unchanged default, `SQLiteConversationStore`
(`runtime/conversation/sqlite/`) is the durable one, structured exactly
like the Engineering Manager's SQLite store (ADR 0004) — the "proven
pattern to copy" this item asked for, copied rather than shared, since
the two applications' persistence needs don't otherwise touch (ADR
0002). Not auto-wired: an integrator assigns it onto
`context.conversations`, the same way `ClaudeProvider` or a
`runtime.tools` tool is registered. Building and testing it against the
real pipeline (not just its own unit tests) found and fixed a real bug
in `AssistantEngine` — see ADR 0018's "A bug this exposed" section. One
database file, not shared with the Engineering Manager, answering the
question this item asked.

### 3. Plugin loading, and capabilities through it — shipped

`PluginLoader` (`runtime/plugins/loader.py`, ADR 0017) discovers
`plugin.py` files under `plugins/` and registers them at
`Runtime.start()` — no configuration flag, since discovery alone has no
side effect. `plugins/engineering_workflow/` is the first plugin loaded
this way. `Plugin.register(registry)` is now the real distribution
mechanism for tools and skills (ADR 0013), not a hook nothing calls. A
plugin that contributes a `Tool` (as opposed to only a `Skill`) is the
next pressure test — it would act under whatever `PermissionPolicy` a
deployment has configured, which the first plugin's skill-only shape
deliberately did not need to reckon with.

### 4. First real tools and skills — shipped

`runtime/tools/` (ADR 0016): `FilesystemTool`, `ShellTool`, `GitTool`,
`DiffTool`, and `TestRunnerTool`, every one a plain `Tool` running
through the existing pipeline unchanged — validated, permission-gated,
timed, and observable from day one, exactly as the pipeline promised.
`ToolAllowlistPolicy` (`runtime/assistant/permissions.py`) is the real
`PermissionPolicy` this milestone anticipated: `AllowAllPolicy` stopped
being honest the moment a tool could genuinely act on the world.
Per-tool user confirmation shipped in item 7 below (`ConfirmationHook`,
ADR 0025), through exactly this seam. Skills shipped too:
`EngineeringWorkflowSkill` (`plugins/engineering_workflow/`, ADR 0017)
is the first genuine skill, teaching a safe order of operations over
the tool suite above. A skill whose `applies_to` opts in automatically,
rather than only activating when a request names it, is the next piece
of this item.

### 5. Richer interfaces

`ConsoleInterface` owns nothing but line I/O; a voice, GUI, or network
interface is the same shape over `AssistantEngine.handle`. Streaming
responses are the one thing that will need design work (ADR 0007) —
everything else fits behind `handle` as it stands. Voice specifically
needs an STT/TTS integration, which needs a provider and credentials
chosen — deferred until that choice is made, not built here.

### 6. Desktop control (highest value for daily use) — shipped

`AppLauncherTool` (`app_launcher`) and `MediaControlTool`
(`media_control`) (`runtime/tools/`, ADR 0024) are the first tools that
act on the desktop rather than a sandboxed project: opening an
application/file/URL by everyday name, and play/pause/skip/mute/volume
by simulating hardware media keys. Both need zero credentials or manual
setup beyond registering them — directly answering the product
direction's own daily-interaction examples ("open Spotify," "pause the
music," "increase volume," "open VS Code"). Neither is auto-registered,
following the ADR 0016 precedent exactly.

Closing/switching applications and listing what is running shipped in
item 11 below (`AppControlTool`, ADR 0026). Still open: Bluetooth and
display management (named in the product vision, not built — different
mechanisms again, not a natural extension of either desktop tool), and
an absolute volume level (needs the Windows Core Audio COM API, which
has no stdlib binding).

### 7. A real, runnable Zeni — shipped

`main.py` is now the composition root (ADR 0025): `Runtime` gained one
generic seam (`on_start`), and `main.py`'s `_wire_zeni` uses it to
register `ClaudeProvider`, the full `runtime/tools/` suite (including
the ADR 0024 desktop tools), a `ToolAllowlistPolicy` naming exactly
those tools, and a new `ConfirmationHook` gating `shell` and
`filesystem`'s `write`/`delete` behind an explicit console approval —
the "no unattended checkpoint" gap flagged when desktop control shipped.
It is a no-op without `ANTHROPIC_API_KEY` set, so nothing about a
credential-less checkout's behavior changed. `assistant_provider =
"claude"` in `configs/config.toml` is still what actually switches to
it, unchanged from the "configuration, not a code change" contract
`README.md` already documented.

Still open: the default `Confirmer` blocks on the console's stdin,
which only the console interface has — a future voice/GUI/network
interface needs its own. A configurable workspace root (today, always
`Path.cwd()`) is the natural next knob if daily use shows the current
working directory isn't the right default.

### 8. Memory (the other first-class product feature) — shipped

`runtime/memory/` (ADR 0027, `docs/memory.md`). Recall is **automatic**:
`AssistantContextAssembler` pulls relevant memories into every brief, so
Zeni already knows things when asked rather than having to look them up
with a tool call. Retrieval scores recency + importance + relevance —
the formula Stanford's Generative Agents established and most production
memory systems still use — with relative time ("yesterday", "last
month") resolved to absolute windows and stripped from the search
subject, the detail the LongMemEval work isolates as highest-leverage.
`MemoryCaptureHook` stores what is worth keeping and skips device
commands; an explicit "remember this" pins the memory so it never decays
out of reach.

Relevance is SQLite FTS5/BM25 rather than embeddings — the one knowing
departure from every system surveyed, forced by the standard-library-only
convention, and drawn behind a seam so an embedding backend is a new
`MemoryStore` and nothing else.

Reconciliation and pruning shipped in item 9 below (ADR 0028). Still
open, and recorded as a deliberate limitation rather than an oversight:
capture is **verbatim, not summarized** — an extraction pass costs a
provider call per exchange and can invent detail the user never said.
Weights and half-life are constructor arguments, not configuration,
until daily use shows the defaults are wrong.

### 9. Memory consolidation — shipped

`runtime/memory/consolidation.py` (ADR 0028) closes the failure mode
ADR 0027 knowingly left open: automatic capture writing something on
every substantive turn is what makes memory work unprompted, and also
what makes it degrade. A `ConsolidationPolicy` seam (write-side, mirroring
`MemoryRetrievalPolicy` read-side) decides ADD / REINFORCE / SUPERSEDE
before every write, so repeating a fact strengthens it rather than
duplicating it, and an explicit correction actually replaces what it
corrects. `MemoryConsolidator.prune` deletes only memories that are
unpinned *and* unimportant *and* never once recalled *and* old —
exposed through `MemoryTool`'s `prune`, behind `ConfirmationHook`, never
automatic.

Deliberately conservative: supersession requires an explicit correction
marker, never similarity alone, because reinforcing wrongly costs
nothing while superseding wrongly destroys a real memory. Semantic
contradiction with no marker ("the battery is LiFePO4", stated flatly
after "the battery is lithium") is therefore **not** detected — that
needs real semantics, and is the natural home for a model-assisted
`ConsolidationPolicy` behind the same seam, where the cost and risk are
opted into rather than paid by default.

### 10. Reflection and synthesis — next

The remaining half of what the memory literature calls consolidation:
Stanford's Generative Agents periodically synthesize clusters of related
memories into higher-level insights ("I have asked about CubeSat power
budgets eleven times → the power subsystem is my current focus"), which
is what lets an assistant answer questions no single stored memory
covers. Everything needed is in place — `MemoryStore.list`, the
`ConsolidationPolicy` seam, and a provider — but unlike everything
shipped so far this genuinely requires model calls, so it needs a
decision about when they run (on a schedule, at session end, on demand)
and what they cost.

### 11. App control: list, switch, close — shipped

`AppControlTool` (`app_control`, `runtime/tools/app_control.py`, ADR
0026) is `AppLauncherTool`'s complement: `list` (every visible window's
title), `switch` (focus a window by name), `close` (force-terminate a
running application by name, via `taskkill`). `close` is the one call in
the entire desktop-control suite that can lose data — it joins `shell`
and `filesystem`'s `write`/`delete` behind `ConfirmationHook` (ADR
0025); `list`/`switch` stay unconfirmed. Registered in `main.py`'s
`_wire_zeni` alongside the rest of the suite.

## Repository-wide

- **Lint/format tooling** — the codebase is hand-consistent; if drift
  appears as more contributors (human or AI) join, adopt ruff as a
  dev-only dependency via an ADR amending the dependency convention.
- **CI** — shipped: `.github/workflows/ci.yml` runs `pip install
  -e ".[dev]" && pytest` on every push to `master` and every pull
  request, against Python 3.12 and 3.13 — the same gate `README.md`
  documents for local development, now enforced on the host the
  repository actually lands on (GitHub).
