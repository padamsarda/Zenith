# Architecture Decision Records

This folder holds the project's Architecture Decision Records (ADRs):
short documents capturing one significant decision each — the context it
was made in, the decision itself, and its consequences. `docs/`
describes how the system **is**; ADRs record **why** it got that way.

## Why ADRs

Two project principles demand them: "important engineering decisions
should be understandable and traceable," and most future implementation
here is expected to be performed by AI systems, which re-derive intent
from the repository alone. An ADR is the cheapest way to stop a future
engineer (human or AI) from either cargo-culting a decision that no
longer applies or accidentally reversing one that still does.

## Conventions

- One decision per file, numbered sequentially:
  `NNNN-short-kebab-title.md`.
- Statuses: `Accepted`, `Superseded by NNNN`, or `Deprecated`. Never
  edit an accepted ADR's decision — write a new ADR that supersedes it.
- Keep them short. Context, Decision, Consequences. A page is plenty.
- Write one whenever a change would make a future reader ask "why is it
  like this?" — new subsystems, layer boundaries, storage choices,
  protocol contracts, dependency policy changes.

## Index

- [0001 — Record architecture decisions](0001-record-architecture-decisions.md)
- [0002 — Two applications over shared infrastructure](0002-two-applications-over-shared-infrastructure.md)
- [0003 — The event system lives in shared/](0003-event-system-lives-in-shared.md)
- [0004 — SQLite for Engineering Manager persistence](0004-sqlite-for-em-persistence.md)
- [0005 — A session-oriented, provider-agnostic provider contract](0005-session-oriented-provider-abstraction.md)
- [0006 — Task lifecycle with two human approval gates](0006-task-lifecycle-and-human-approval-gates.md)
- [0007 — Synchronous core, no async framework](0007-synchronous-core-no-async.md)
- [0008 — Execution engine: a reconcile-and-advance tick](0008-execution-engine-reconcile-and-advance.md)
- [0009 — Plans, and a task graph that may evolve](0009-plans-and-the-evolving-task-graph.md)
- [0010 — Context flows between sessions as deterministic assembly](0010-deterministic-context-assembly.md)
- [0011 — A turn-oriented assistant provider contract, separate from the Engineering Manager's](0011-turn-oriented-assistant-provider-contract.md)
- [0012 — The assistant pipeline: one path from request to reply](0012-assistant-pipeline-one-path-from-request-to-reply.md)
- [0013 — Capabilities: tools act, skills instruct](0013-tools-act-skills-instruct.md)
