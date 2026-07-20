# 0009 — Plans, and a task graph that may evolve

- Status: Accepted
- Date: 2026-07-20

## Context

Tasks answered "what is one unit of work?" but nothing represented the
question a human actually brings: a *goal* ("ship plugin support") that
becomes many ordered tasks. Without that level, approval was
per-task busywork, completion of a goal was unobservable, and the
dependency graph was frozen at creation time — a task could never gain
a predecessor, so work discovered mid-execution ("we also need a
migration first") could not reshape anything. ADR 0006 kept cycles
impossible by allowing dependencies only on pre-existing tasks, and any
evolution mechanism must preserve that safety.

## Decision

**Plans.** A `Plan` (`domain/plan.py`) is one goal in one project,
decomposed into tasks via `Task.plan_id` (nullable — standalone tasks
remain first-class). Lifecycle: `DRAFT -> IN_PROGRESS -> COMPLETED`,
`CANCELLED` from either. Three rules connect plans to execution:

- `approve_plan` is **gate one in bulk**: it moves the plan to
  IN_PROGRESS and every DRAFT task in it to READY. An empty plan
  cannot be approved — a goal must be decomposed before it can run.
- A task belonging to a plan is only *eligible for dispatch* while its
  plan is IN_PROGRESS. Task-level approval still works, but nothing in
  an unapproved plan executes.
- A plan **completes itself**: when the last of its tasks reaches a
  terminal status through the facade, the plan transitions to
  COMPLETED. Gate two stays per-task — accepting the final piece of
  work is what finishes the goal.

**The graph may grow.** `add_task_dependency` lets an existing task
gain a predecessor, guarded three ways: the domain allows it only while
the task is still schedulable (DRAFT, READY, FAILED), the facade
rejects cross-project and cancelled dependencies, and an explicit
cycle check (`orchestration/graph.py`, `would_create_cycle`) replaces
the by-construction guarantee the moment it no longer holds. Tasks may
also join an IN_PROGRESS plan — discovered work lands in the running
plan, re-opening its completion condition.

`graph.py` also derives the execution structure rather than storing
it: `execution_waves` (what may run in parallel; ordering within a
wave mirrors dispatch order) and `blockages` (tasks whose
dependencies still block them — or can never complete, because a
dependency was cancelled).

## Consequences

- A goal is now one approval, one observable completion, and one
  audit trail — not N of each.
- Execution order and parallelism are *derived from the graph on
  demand*, never persisted, so they cannot drift from the truth.
- Planning itself (decomposing a goal into tasks) remains a human or
  AI activity outside the engine; a future planning-provider session
  can write plans through the same facade without new mechanisms.
- Cancelled dependencies no longer silently strand dependents:
  `blocked_tasks` names them and why.
- Schema migration 2 (plans table, `tasks.plan_id`,
  `sessions.resume_at`) upgrades existing databases in place,
  append-only per ADR 0004.
