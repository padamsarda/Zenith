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

### 1. First real provider adapter (highest value)

A `Provider` implementation that drives Claude Code as a subprocess,
generalizing `engineering_tools/watchdog`: start a session in a
project's working directory (`start_session`), detect completion and
session limits (`check_session` reporting `LIMIT_REACHED` with
`resume_at`), resume with `--continue` (`resume_session`), terminate
(`stop_session`). The watchdog's parsing logic (limit detection, reset
times) is proven and should be extracted, tested, and reused rather
than rewritten. A second adapter (e.g. an HTTP-API provider) will then
pressure-test the contract's provider-agnosticism; extend
`Provider`/`SessionSpec` additively if it falls short (ADR 0005).
With one real adapter, expose `run` in the CLI — the engine
(`manager.run()`) is already the whole loop.

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

### 1. First real assistant provider (highest value)

An `AssistantProvider` implementation calling a real API. One method,
`generate_turn`, mapping `TurnBrief` to `AssistantTurn`: history to
the vendor's message format, the `CapabilityCatalog` to its tool
schema, its response back to text and `ToolCall`s. `ScriptedProvider`
is the executable spec. A second adapter will pressure-test the
contract's provider-agnosticism; extend it additively if it falls
short (ADR 0011). Whether `ToolParameter` needs a real type vocabulary
(JSON Schema) will be answered here, not before.

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

### 4. First real tools and skills

Assistant behaviors as registered `Tool`s and `Skill`s. Every one runs
through the pipeline, so it is validated, permission-gated, timed, and
observable from day one. The first tool that can genuinely act on the
world is also what makes `AllowAllPolicy` inadequate — a real
`PermissionPolicy` (allowlists, per-tool confirmation) belongs with
it, not before it.

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
