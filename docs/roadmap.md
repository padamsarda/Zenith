# Roadmap

Where this repository is headed, in dependency order. Each item builds
on what exists; none requires reworking current foundations. This file
is direction, not commitment — reorder freely, but record significant
design choices as ADRs (`architecture/`) when implementing.

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

### 5. Zenith as a managed project

The closing of the loop: a `zenith` project whose plans are Zenith
milestones, dispatched to providers by the Engineering Manager. No new
mechanism is expected — this is dogfooding, and the friction it finds
feeds items 1–4. Items 6 and 7 below (verification, reports) are
exactly the hardening this dogfooding would otherwise discover the hard
way — landing them first means the first real dogfood run has something
to trust and something to read afterward.

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
report from durable state (plans, task breakdown, work needing review,
blockages, recent attention, session outcomes); `project report
<id> [--out PATH]` in the CLI.

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
Per-tool user confirmation remains open — a `before_tool` `AssistantHook`
is the seam for it, not a new mechanism. Skills shipped too:
`EngineeringWorkflowSkill` (`plugins/engineering_workflow/`, ADR 0017)
is the first genuine skill, teaching a safe order of operations over
the tool suite above. A skill whose `applies_to` opts in automatically,
rather than only activating when a request names it, is the next piece
of this item.

### 5. Richer interfaces

`ConsoleInterface` owns nothing but line I/O; a voice, GUI, or network
interface is the same shape over `AssistantEngine.handle`. Streaming
responses are the one thing that will need design work (ADR 0007) —
everything else fits behind `handle` as it stands.

## Repository-wide

- **Lint/format tooling** — the codebase is hand-consistent; if drift
  appears as more contributors (human or AI) join, adopt ruff as a
  dev-only dependency via an ADR amending the dependency convention.
- **CI** — shipped: `.github/workflows/ci.yml` runs `pip install
  -e ".[dev]" && pytest` on every push to `master` and every pull
  request, against Python 3.12 and 3.13 — the same gate `README.md`
  documents for local development, now enforced on the host the
  repository actually lands on (GitHub).
