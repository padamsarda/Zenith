# 0002 — Two applications over shared infrastructure

- Status: Accepted
- Date: 2026-07-20

## Context

The long-term vision has two systems: **Zenith**, the assistant runtime
(`runtime/`), and the **Engineering Manager**, a local-first platform
that orchestrates AI-performed engineering work across projects and
providers. Eventually Zenith should become just one project managed by
the Engineering Manager. A project principle fixes the relationship:
engineering orchestration remains independent of the Zenith runtime.
Both systems are expected to evolve continuously — Zenith gaining
user-facing capabilities, the Engineering Manager gaining orchestration
capability — so neither may constrain the other's growth.

Options considered: (a) build the Engineering Manager inside `runtime/`
as a Zenith capability; (b) a separate repository; (c) a sibling
package in this repository over a shared infrastructure layer.

## Decision

Option (c). The repository hosts two applications:

- `runtime/` — the Zenith assistant runtime.
- `engineering_manager/` — the Engineering Manager.

with `shared/` as the **only** layer both may depend on. `shared/`
contains nothing specific to either application (exceptions, event
system, small utilities). Import rules, enforced by review:

- `engineering_manager/` never imports `runtime/` or `configs/`.
- `runtime/` never imports `engineering_manager/`.
- `shared/` imports neither.
- `engineering_tools/` (standalone developer utilities) imports none of
  the above.

## Consequences

- The Engineering Manager can orchestrate Zenith the way it will
  orchestrate any other repository — from the outside — which is the
  end state the vision requires.
- Generic infrastructure must be hoisted to `shared/` before both
  applications can use it (see ADR 0003); this is deliberate friction
  that keeps the boundary honest.
- Either application can later move to its own repository by lifting
  its package plus `shared/`, without disentangling imports.
- One repository means one test suite, one set of conventions, and one
  place for AI contributors to learn both systems — right for the
  current team size; superseded when the systems need independent
  release cadences.
