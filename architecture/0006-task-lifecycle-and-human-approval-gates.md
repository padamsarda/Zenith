# 0006 — Task lifecycle with two human approval gates

- Status: Accepted
- Date: 2026-07-20

## Context

The Engineering Manager exists to remove the human from mechanical
coordination while keeping the human responsible for direction and
approval. That balance has to be structural, not aspirational —
encoded in what state transitions are possible.

## Decision

Tasks move through a validated state machine
(`engineering_manager/domain/`):

```
DRAFT -> READY -> IN_PROGRESS -> NEEDS_REVIEW -> DONE
            ^          |               |
            |          +-> FAILED -----+-> READY (retry / rework)
            |          +-> READY (abandoned session)
            +--- DRAFT (revise)        any non-terminal -> CANCELLED
```

- Exactly two transitions are human approval gates, exposed as explicit
  facade methods: `approve_task` (DRAFT -> READY, "yes, do this") and
  `accept_task` (NEEDS_REVIEW -> DONE, "yes, the work is good").
- `IN_PROGRESS -> DONE` does not exist: no work completes without
  review.
- Failure is not terminal for the work: `FAILED -> READY` (retry) and
  `NEEDS_REVIEW -> READY` (rework) keep tasks recoverable; only `DONE`
  and `CANCELLED` are terminal.
- Eligibility for dispatch = `READY` + project `ACTIVE` + all
  dependencies `DONE`. Dependencies must exist (in the same project)
  when a task is created, which makes dependency cycles impossible by
  construction — a new task cannot yet be anyone's dependency.
- Sessions have their own lifecycle (`ACTIVE <-> INTERRUPTED`, ending
  `COMPLETED`/`FAILED`/`ABANDONED`); the dispatcher keeps task and
  session state in lockstep.

## Consequences

- Everything between the two gates can run unattended today, and
  adding more autonomy later (auto-review policies, trusted task
  classes) means widening specific transitions deliberately — each such
  widening is a visible, reviewable decision.
- The state machine is enforced in the domain layer, so no interface
  (CLI, API, UI, or future scheduler) can construct an illegal
  shortcut.
- Per-task review policy (e.g. auto-accept for low-risk tasks) is an
  anticipated future ADR, not a hidden flag.
