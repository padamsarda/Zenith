# 0003 — The event system lives in shared/

- Status: Accepted
- Date: 2026-07-20

## Context

The in-process event system (`Event`, `EventBus`, `EventLogger`) was
built inside `runtime/events/` for the Zenith runtime's lifecycle. The
Engineering Manager needs the same primitives for its domain events, and
ADR 0002 forbids it from importing `runtime/`. The event system contains
nothing assistant-specific.

## Decision

Move the generic event system to `shared/events/` (and `EventBusError`
to `shared.exceptions`). Each application defines its own concrete event
types next to their emitters: `runtime/events/lifecycle_events.py`,
`runtime/commands/events.py`, `runtime/plugins/events.py`,
`engineering_manager/events.py`.

## Consequences

- Both applications share one proven pub/sub implementation and one
  set of event semantics (type-exact dispatch, subscription order,
  listener exception isolation).
- Concrete event types stay application-private; subscribing across
  applications would require a deliberate new decision, not an import
  of convenience.
- Precedent: infrastructure generic enough to be wanted by both
  applications is hoisted to `shared/`, not duplicated and not imported
  across the application boundary.
