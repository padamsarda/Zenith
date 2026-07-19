# 0007 — Synchronous core, no async framework

- Status: Accepted
- Date: 2026-07-20

## Context

Both applications will eventually juggle concurrent activity: the
runtime reacting to events, the Engineering Manager tracking multiple
provider sessions at once. The obvious modern reflex is asyncio
throughout. But the actual long-running work happens **outside** these
processes — in provider services and subprocesses — and what this code
does is bookkeeping: fast, local, sequential state changes. The
codebase is also maintained largely by AI systems across sessions, and
synchronous code is simpler to reason about, test, and extend safely.

## Decision

Keep every core API synchronous. The `EventBus` dispatches on the
calling thread; the `Store` performs blocking SQLite calls; the
`Provider` contract is poll-based (`check_session`), not
callback-based. Concurrency, when it arrives, lives at the **edges**:
a scheduler loop that polls sessions, OS processes for real provider
work, threads inside a specific provider implementation if it needs
them — never an async runtime the whole codebase must adopt.

## Consequences

- Deterministic tests (674 of them run in ~2 seconds) and no colored
  functions, event-loop lifecycle, or async-safe locking to maintain.
- Multiple in-flight sessions are already representable — sessions are
  rows with state, not live objects — so "concurrent" orchestration is
  a polling loop over persisted state, which a single thread handles
  comfortably at this scale.
- If a future component genuinely needs an event loop (e.g. a
  WebSocket-based UI), it wraps the synchronous core at its edge; a
  move to an async core would supersede this ADR.
