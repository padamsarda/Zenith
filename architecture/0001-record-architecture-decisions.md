# 0001 — Record architecture decisions

- Status: Accepted
- Date: 2026-07-20

## Context

The project's stated principles require that important engineering
decisions be understandable and traceable, and the `architecture/`
folder existed for "design records" but was empty. Future implementation
is expected to be performed largely by AI systems working from the
repository alone; undocumented intent is intent lost between sessions.

## Decision

Record every significant architectural decision as a numbered ADR in
`architecture/`, following the conventions in `architecture/README.md`.
Accepted ADRs are immutable; reversals happen by superseding.

## Consequences

- The "why" behind the codebase survives contributor and session
  turnover.
- Reviewing a proposed change includes checking whether it contradicts
  an accepted ADR — and if it does, the change must supersede it
  explicitly rather than silently.
- Writing an ADR is part of the definition of done for architectural
  work.
