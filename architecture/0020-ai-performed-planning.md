# 0020 — AI-performed planning through an ordinary Provider session

- Status: Accepted
- Date: 2026-07-21

## Context

ADR 0009 gave a goal a durable representation (`Plan`) but left
decomposing that goal into tasks a human activity, noting explicitly:
"a future planning-provider session can write plans through the same
facade without new mechanisms." Until this landed, giving the
Engineering Manager a high-level objective required a human to already
have broken it into tasks and dependencies before anything could run —
the first, and largest, obstacle to "give it a goal and walk away."

## Decision

`EngineeringManager.plan_from_goal(project_id, goal, provider_id,
account_id, ...)` does exactly what ADR 0009 anticipated:

1. Records the goal as an ordinary `DRAFT` plan (`add_plan` — unchanged).
2. Runs one bounded, synchronous session through the *existing*
   `Provider` contract (ADR 0005), asking it to decompose the goal into
   a JSON task array (`orchestration/planning.py`,
   `PlanningSessionRunner`). This is deliberately not the
   `Dispatcher`/`ExecutionEngine` tick machinery: a planning session is
   one request-response exchange a caller is actively waiting on (a CLI
   invocation, a future API call), not a multi-hour engineering session
   to be driven across ticks with retry and interruption handling.
   `LIMIT_REACHED`/`AWAITING_INPUT` are therefore reported as failures
   here, not interruptions to resume later.
3. Parses the output (`orchestration/planning_decomposition.py`,
   `parse_decomposition`) tolerantly — markdown fences and surrounding
   prose are stripped, and a malformed item is skipped rather than
   failing the whole decomposition.
4. Writes the result through the *same* `add_task`/`add_task_dependency`
   the facade already exposes to a human. A dependency edge the model
   named that would form a cycle, or points at an invalid index, is
   logged and skipped rather than raised — the plan still lands, for a
   human to fix up.

The plan is `DRAFT` throughout, with every task `DRAFT`. `approve_plan`
remains the only way anything in it becomes eligible for dispatch — the
gate ADR 0009 already established is exactly what makes an AI-authored
decomposition safe to accept sight-unseen into the store: nothing in it
can run without a human approving the plan first.

One contract wrinkle: `SessionSpec.task` is a required field, but a
planning session has no `Task` yet. Rather than widening the `Provider`
contract (ADR 0005 permits this additively, but no shipped provider
implementation reads `spec.task` at all today), a transient `Task` is
constructed to satisfy the shape and never persisted. If a future
provider needs to *use* `spec.task` for planning specifically, that is
the trigger to revisit this, not before.

A new event, `PlanDecomposed` (payload: `plan_id`, `project_id`,
`task_count`), is published on success, following the existing
event-naming convention.

## Consequences

- The Engineering Manager can now be handed a goal with no pre-existing
  tasks and produce a reviewable plan unattended — the roadmap's
  highest-value remaining item for the "walk away for hours" mission.
- A failed or malformed decomposition still leaves an auditable `DRAFT`
  plan (empty, or partially populated) rather than nothing — the same
  state a human abandoning a decomposition mid-way would leave, and
  `OrchestrationError` propagates so a caller (CLI, future API) can
  report exactly what went wrong.
- Planning trusts no output: JSON parsing is defensive, dependency
  wiring re-uses the same cycle guard (`orchestration/graph.py`) that
  protects a human's edits, and nothing decomposed this way can dispatch
  without `approve_plan`.
- `PlanningSessionRunner` is intentionally separate from
  `Dispatcher`/`ExecutionEngine` — planning is synchronous-and-waited-on,
  execution is asynchronous-and-ticked. Conflating them would have
  forced planning through retry/interruption machinery built for a
  different kind of session.
