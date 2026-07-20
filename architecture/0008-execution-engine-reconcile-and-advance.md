# 0008 — Execution engine: a reconcile-and-advance tick

- Status: Accepted
- Date: 2026-07-20

## Context

The foundation (ADRs 0004–0007) could represent long-running work but
not drive it: a human had to poll sessions, resume after provider
limits, retry failures, and dispatch freed capacity. The missing piece
was the orchestration loop itself — and its design determines whether
execution survives crashes, provider limits, and weeks-long workflows,
or degrades into per-provider special cases. Several shapes were
possible: callback-driven (providers push events), daemon-with-state
(the loop holds progress in memory), or reconciliation (all state in
the store, a stateless loop that compares it with provider truth).

## Decision

`ExecutionEngine` (`orchestration/engine.py`) advances everything
through one synchronous, deterministic `tick()` with a fixed phase
order:

1. **Reconcile** every ACTIVE session against `check_session`:
   `FINISHED` completes it (the provider's `detail` becomes the session
   summary), `FAILED` fails it, `LIMIT_REACHED` interrupts it with a
   `resume_at` (the provider's, or now + a configured backoff),
   `AWAITING_INPUT` interrupts it with **no** `resume_at` and publishes
   `AttentionRequired`. A provider that *raises* on check has lost the
   session: it is failed and recovered like any other failure.
2. **Resume** every INTERRUPTED session whose `resume_at` has passed.
   `resume_at is None` means a human must resume — the engine never
   auto-resumes a session that is waiting on input.
3. **Retry** every FAILED task the `RetryPolicy` approves
   (`orchestration/retry.py`; default `LimitedRetryPolicy`, three
   attempts). Attempt counts are *derived* from the persisted session
   history, never stored. Exhausted tasks stay FAILED for a human;
   `AttentionRequired` fires once, when the failure happens.
4. **Dispatch** eligible tasks until none remain or accounts saturate.

The engine holds no state between ticks; every fact it acts on lives in
the store. `run()` is only `tick()` on an interval with an injectable
`sleep` — all decisions stay inside the tick (ADR 0007). Ticks report
what changed as a frozen `TickReport`.

## Consequences

- **Crash recovery is not a feature** — it is the absence of one. After
  a restart, the next tick reconciles persisted sessions against
  provider truth exactly like any other tick. There is no recovery
  code path to test separately or to rot.
- A tick with scripted providers and a scripted clock is fully
  deterministic, so multi-day scenarios (limit at hour 5, resume, crash,
  retry, finish) are ordinary unit tests.
- Providers stay dumb: they report facts (`ProviderSessionStatus`);
  every decision — resume timing, retry budgets, who gets dispatched —
  lives in the engine and its policy seams. A new provider adds zero
  orchestration logic.
- `check_session` gains a contract clarification: raise only when the
  session is genuinely lost; absorb transient trouble. Documented on
  `Provider.check_session`.
- Polling latency is bounded by the tick interval; acceptable for work
  measured in minutes to weeks. If sub-second reaction is ever needed,
  a push channel would wrap the engine at its edge, superseding
  nothing.
