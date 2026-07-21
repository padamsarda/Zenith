# 0019 — A verification gate between a provider's FINISHED and NEEDS_REVIEW

- Status: Accepted
- Date: 2026-07-21

## Context

ADR 0006 made `NEEDS_REVIEW -> DONE` a human gate deliberately: no work
completes without review. But nothing stood between a provider claiming
`FINISHED` and a task reaching `NEEDS_REVIEW` — the engine trusted the
claim outright. For a human reviewing every task promptly, that gap is
invisible. For the stated goal of this repository's next phase — running
the engine unattended for hours on a real objective — it is the single
biggest reason not to trust it: broken work reaches `NEEDS_REVIEW`
indistinguishable from good work, and sits there until a human happens
to look. The retry loop (ADR 0008) already recovers from a provider
*admitting* failure; it had no way to recover from a provider being
wrong about success.

## Decision

Add `VerificationPolicy` (`orchestration/verification.py`), a seam of
the same shape as `AssignmentPolicy` and `RetryPolicy`: the engine
supplies the facts (the task, its project), the policy decides
(`VerificationResult`: `passed`, `detail`).

- `NoVerificationPolicy` is the default — always passes. Behavior for
  every existing caller is unchanged unless a policy is configured.
- `CommandVerificationPolicy` runs a command (default `python -m
  pytest`) in the project's root, synchronously, with a timeout; a
  zero exit passes, anything else — including a timeout or a missing
  project directory — fails, with captured output as `detail`.

`ExecutionEngine._reconcile_active_sessions` calls the policy exactly
once, at the moment a provider reports `FINISHED`, before deciding
between `complete_session` and `fail_session`. A failed verification
routes through `fail_session` — the *same* path a provider's own
`FAILED` report takes. This was the key design choice: verification
failure is not a new outcome kind requiring new states, events, or
`TickReport` fields. It is folded into the retry loop that already
exists, so a task that fails verification is retried, backed off, and
eventually escalated via `AttentionRequired` exactly like any other
failure — no engine phase, dispatcher method, or domain transition
needed to change.

`ExecutionEngine.set_verification_policy` (mirroring
`AssistantEngine.set_permission_policy` in the runtime) lets a caller
configure the policy after construction — the CLI's `run --verify-command`
needs this, since the engine is built before arguments naming a command
are parsed.

## Consequences

- Trusting the engine to run unattended no longer requires trusting
  every provider's self-report; a configured command is the check.
- The check is synchronous and bounded (`timeout_seconds`), which favors
  fast, focused verification (a lint pass, a targeted test subset) over
  a full slow suite — a slow suite belongs in the provider's own session,
  not blocking the tick.
- A verification failure and a provider failure are indistinguishable in
  `TickReport`/events today (both are `sessions_failed`); a future reader
  wanting to tell them apart reads the session's `summary`, which for a
  verification failure begins with the policy's own detail. Distinguishing
  them structurally is deferred until something needs it.
- `CommandVerificationPolicy` is one useful implementation, not the only
  one; a policy that re-uses the dispatched provider itself to ask "does
  this look right?" is a natural next one, needing no engine change.
