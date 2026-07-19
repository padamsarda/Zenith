# 0004 — SQLite for Engineering Manager persistence

- Status: Accepted
- Date: 2026-07-20

## Context

The Engineering Manager is local-first and must remember projects,
tasks, sessions, accounts, and an audit trail across process restarts —
"resume interrupted work" is a core requirement. The repository's
dependency policy is standard library only (pytest as the sole dev
dependency). Options considered: JSON/TOML files per entity, an
event-sourced log with rebuilt state, an ORM over a database, and plain
`sqlite3` from the standard library.

## Decision

Use `sqlite3` with hand-written SQL behind a single `Store` class
(`engineering_manager/store/`):

- Schema is versioned via SQLite's `user_version` pragma; `MIGRATIONS`
  is an append-only tuple of scripts, applied in order on open. Schema
  changes are always new migrations, never edits to shipped ones.
- Domain objects map to rows in a dedicated serialization module; the
  domain layer knows nothing about persistence.
- `add_*` fails on duplicates, `update_*` fails on missing rows — no
  upserts, so intent is always explicit and silent overwrites are
  impossible.
- State tables are the source of truth; the `event_log` table is an
  append-only audit trail, not an event-sourcing mechanism.
- Task dependencies are stored as a JSON array column, not a join
  table — at the current scale eligibility is computed in memory, and a
  join table can be introduced by a later migration if SQL-side
  dependency queries are ever needed.
- Each store method commits before returning. Multi-call consistency
  (a unit-of-work spanning dispatch's task update + session insert) is
  a known deferral, acceptable while a single process owns the
  database; revisit when there are concurrent writers.

## Consequences

- Durable, transactional, queryable state with zero new dependencies
  and a single file the user can back up or inspect.
- Migrations make evolution routine: growing the schema is the normal
  path, not a breaking event — old databases upgrade on open, and a
  database from newer code is refused loudly rather than corrupted.
- Hand-written SQL keeps every query visible and reviewable; if the
  method count grows painful, that pain is the signal to reconsider,
  not a reason to pre-adopt an ORM now.
