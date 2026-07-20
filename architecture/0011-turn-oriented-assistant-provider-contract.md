# 0011 — A turn-oriented assistant provider contract, separate from the Engineering Manager's

- Status: Accepted
- Date: 2026-07-20

## Context

Zenith must talk to AI providers (Claude, Gemini, Codex, OpenAI, local
models) to answer users, and the Engineering Manager already has an
accepted, provider-agnostic `Provider` contract (ADR 0005). The obvious
move is to reuse it — one provider abstraction for the whole
repository, registered once, implemented once per vendor.

It is the wrong move, because the two systems buy different things from
the same vendors. The Engineering Manager's unit of work is a
long-running engineering **session**: it starts work, polls it, survives
session limits, and resumes hours later — `start_session`,
`check_session`, `resume_session`, `stop_session`, with
`LIMIT_REACHED` and `resume_at` as first-class concepts. Zenith's unit
of work is a single conversational **turn**: given the conversation so
far and the capabilities available, produce the next assistant
response, now, while a user waits. Nothing in Zenith's flow polls, and
nothing in the Engineering Manager's flow is interactive.

Forcing both onto one interface means every assistant integration
implements three session methods it will never use, or the contract
grows a union of both vocabularies and each implementation ignores
half. Either way the abstraction stops describing anything.

## Decision

Zenith gets its own contract, `runtime/providers/base.py`, deliberately
parallel to ADR 0005 in *shape* but disjoint in *vocabulary*:

- `AssistantProvider` is an ABC with `provider_id`, `name`, and one
  operation: `generate_turn(brief) -> AssistantTurn`.
- Input is a `TurnBrief` (conversation ID, message history,
  instructions, capability catalog, plus a `metadata` dict as the
  provider-specific extension point, exactly as `SessionSpec.metadata`
  serves ADR 0005).
- Output is an `AssistantTurn` carrying text, `ToolCall`s, or both.
  Text alone ends the request; tool calls drive another turn.
- Implementations must fail honestly: `AssistantProviderError` rather
  than an empty or misleading turn. Credentials are resolved inside the
  implementation, never stored by the runtime.
- `ScriptedProvider` is the executable specification and universal test
  double (the counterpart of `InMemoryProvider`); `EchoProvider` is the
  built-in default so the pipeline is exercisable with no integration
  present.

The two contracts stay in their own applications, and neither moves to
`shared/`. ADR 0002 already forbids `runtime/` and
`engineering_manager/` importing each other, so sharing would require
promoting a provider abstraction into `shared/` — which is reserved for
code genuinely generic to both, and a union of two disjoint
vocabularies is not that.

## Consequences

- A vendor that serves both systems is integrated twice, against two
  small interfaces (one method here, four there). This is accepted: the
  duplicated part is credential resolution and transport, while the
  parts that differ — session resumption versus turn generation — are
  exactly what each contract exists to express.
- The runtime is provably provider-independent the same way
  orchestration is: the whole assistant pipeline is tested end-to-end
  with no real provider in the repository.
- Both contracts grow additively as real integrations demand
  (streaming, token accounting, richer capability negotiation), and
  neither constrains the other's evolution.
- If a genuinely shared concept emerges later (credential resolution,
  rate-limit accounting), it can move to `shared/` on its own merits
  without dragging either contract with it.
