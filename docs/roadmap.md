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

### 2. AI-performed planning

Plans are the representation (ADR 0009); decomposition is still a
human activity. A planning session — any provider asked to break a
goal into tasks and dependencies, written through the facade — closes
that gap with no new mechanism. Worth an ADR when it lands: how
decompositions are reviewed (the plan's DRAFT state is the natural
gate).

### 3. Richer assignment and retry policies

`FirstAvailablePolicy` ignores cost, capability, and history;
`LimitedRetryPolicy` ignores failure kind and backoff. Add policies
using per-provider concurrency limits, model/task matching
(`SessionSpec.model` is already plumbed), past outcomes (the event log
already records them), and failure-aware retry delays. Both seams
absorb this without engine or dispatcher changes.

### 4. Store hardening as concurrency arrives

When the engine loop and CLI can write concurrently: a unit-of-work
(one transaction spanning dispatch's task update + session insert),
`busy_timeout`, and possibly a join table for dependencies if SQL-side
queries become useful (ADR 0004 anticipates all three).

### 5. Zenith as a managed project

The closing of the loop: a `zenith` project whose plans are Zenith
milestones, dispatched to providers by the Engineering Manager. No new
mechanism is expected — this is dogfooding, and the friction it finds
feeds items 1–4.

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

### 2. Durable conversations

`ConversationStore` is in-memory, so history dies with the process.
Persistence is a store implementation behind the same interface — the
Engineering Manager's SQLite store (ADR 0004) is the proven pattern to
copy. Briefs are already assembled from durable state (ADR 0010's
principle), so nothing else changes. Worth an ADR when it lands:
whether both applications share one database file.

### 3. Plugin loading, and capabilities through it

Discovery/import from `plugins/` into the existing `PluginRegistry`;
the framework and events already exist. This is what makes
`Plugin.register(registry)` the real distribution mechanism for tools
and skills (ADR 0013) rather than a hook nothing calls.

### 4. First real tools and skills — shipped

`runtime/tools/` (ADR 0016): `FilesystemTool`, `ShellTool`, `GitTool`,
`DiffTool`, and `TestRunnerTool`, every one a plain `Tool` running
through the existing pipeline unchanged — validated, permission-gated,
timed, and observable from day one, exactly as the pipeline promised.
`ToolAllowlistPolicy` (`runtime/assistant/permissions.py`) is the real
`PermissionPolicy` this milestone anticipated: `AllowAllPolicy` stopped
being honest the moment a tool could genuinely act on the world.
Per-tool user confirmation remains open — a `before_tool` `AssistantHook`
is the seam for it, not a new mechanism. Skills remain unstarted; the
first genuine skill (as opposed to a tool) is the next piece of this
item.

### 5. Richer interfaces

`ConsoleInterface` owns nothing but line I/O; a voice, GUI, or network
interface is the same shape over `AssistantEngine.handle`. Streaming
responses are the one thing that will need design work (ADR 0007) —
everything else fits behind `handle` as it stands.

## Repository-wide

- **Lint/format tooling** — the codebase is hand-consistent; if drift
  appears as more contributors (human or AI) join, adopt ruff as a
  dev-only dependency via an ADR amending the dependency convention.
- **CI** — `pip install -e ".[dev]" && pytest` is the whole gate; wire
  it to whichever host the repository lands on.
