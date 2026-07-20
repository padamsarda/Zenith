# 0010 — Context flows between sessions as deterministic assembly

- Status: Accepted
- Date: 2026-07-20

## Context

Engineering work spanning days and many sessions needs knowledge to
survive session boundaries: what prerequisite work concluded, what
previous attempts at a task tried and why they failed, what goal the
task serves. The roadmap deferred this as "session context handoff"
and posed the design question: is context a stored artifact (a
document per task, maintained by providers or a distilling model) or
something derived? Stored context can go stale, needs an author, an
update protocol, and size management — machinery with no proven need
yet.

## Decision

Context is **assembled, not stored**. `ContextAssembler`
(`orchestration/context.py`) composes each session's instruction brief
deterministically from durable state alone: the project, the plan
goal, the task description, the summaries of DONE dependencies'
completing sessions, and the summaries of this task's failed or
abandoned attempts. The dispatcher uses it for every dispatch unless
explicit instructions are passed.

The only interchange format is the session `summary` — written when a
session ends (for engine-driven completion, the provider's final
`detail` becomes the summary). Providers therefore influence future
context exclusively by summarizing well, through the existing
contract; no new provider obligation, table, or document store exists.

## Consequences

- Identical store state produces an identical brief — reproducible,
  restart-proof, and provider-independent by construction.
- Retries automatically know their own failure history, and dependent
  tasks automatically receive their prerequisites' conclusions; the
  "session 40 of a week-long plan" brief costs the same as session 1.
- Quality of context is bounded by quality of summaries. If summaries
  prove too thin, the upgrade path is richer *inputs* to the same
  assembler (e.g. a structured completion report on the session), not
  a switch to stored context — that would supersede this ADR.
- Brief size grows with dependency count and attempt count, which is
  bounded and small in practice; truncation policy is deferred until a
  real provider shows a real limit.
