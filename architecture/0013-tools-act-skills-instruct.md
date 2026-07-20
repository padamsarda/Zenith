# 0013 — Capabilities: tools act, skills instruct

- Status: Accepted
- Date: 2026-07-20

## Context

"What Zenith can do" covers two genuinely different things, and
conflating them is the standard way assistant runtimes become
unextensible.

Some capabilities *act*: read a file, send a message, launch an
application. They take arguments, produce a result, and can fail. A
provider needs to know they exist, call them by name, and see what
happened.

Others are *know-how*: how to write a commit message in this
repository, how to summarize a document, what tone to use with this
user. They execute nothing. They shape how the model behaves.

A single "capability" abstraction covering both ends up with an
`execute` method that half the implementations no-op, or an
`instructions` field that half of them leave empty — and the runtime
can no longer tell which kind it is holding, so it cannot treat either
correctly.

## Decision

Two base classes, one registry each, one shared discovery surface.

- **`Tool`** (`runtime/capabilities/tool.py`) is invocable:
  `tool_id`, `name`, `description`, declared `parameters`, and
  `invoke(command_context, arguments)`. Tools never run themselves —
  the engine invokes each one as a `Command` (ADR 0012).
- **`Skill`** (`runtime/capabilities/skill.py`) is instructional:
  `skill_id`, `name`, `description`, and
  `instructions(request) -> str`. A skill is active for a request if
  the request names it (`metadata["skills"]`) or its own
  `applies_to(request)` opts in. Active skills' instructions are
  composed into the provider's brief.
- **`ToolRegistry` / `SkillRegistry`** mirror `ServiceRegistry`:
  explicit `register`/`unregister`/`get`/`has`/`list`, validation at
  the boundary, events on the bus, no discovery and no magic.
- **`CapabilityCatalog`** is the single discovery surface. It is built
  on demand by `build_catalog` as immutable `CapabilityDescriptor`s,
  sorted by capability ID — never cached, so it cannot go stale, and
  identical for identical registrations regardless of registration
  order. Providers receive descriptors, never the objects, so no
  provider can invoke a tool directly or bypass the pipeline.

Skill instructions must be deterministic for a given request. This is
ADR 0010's principle (context assembled from durable state at the
moment it is needed, never stored) applied to assistant behavior: a
brief must be reproducible from the same state, and a skill that
answered differently each call would break that.

A behavior needing both ships a skill and the tools it teaches the
provider to use. They compose; neither subsumes the other.

## Consequences

- Adding a capability is subclassing one of two small ABCs and calling
  `register` — no pipeline, engine, or provider change.
- The runtime can reason about each kind correctly: tools are gated by
  the `PermissionPolicy` and executed as commands; skills are composed
  into text and never executed at all. There is no permission question
  about a skill, and no prompt question about a tool.
- Providers see a stable, declarative view of capabilities and cannot
  reach past it.
- Descriptors are deliberately thin — parameters carry a name, an
  optional description, and a required flag, with no type vocabulary.
  A real integration that needs JSON Schema will extend
  `ToolParameter` additively, which is cheaper than retiring a rich
  speculative one (the same reasoning as ADR 0005).
- Plugins become the natural distribution mechanism: a plugin's
  `register(registry)` hook is where it contributes its tools and
  skills.
