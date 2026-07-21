# 0028 — Memory consolidation: merging repeats, correcting facts, pruning the dead

- Status: Accepted
- Date: 2026-07-21

## Context

ADR 0027 made memory automatic: everything substantive the user says is
captured without being asked, and relevant memories are recalled into
every brief. That is what makes it work unprompted, and it is also
exactly what makes it degrade with use — a property ADR 0027 recorded as
a known limitation rather than solved.

Two failures compound over daily use:

1. **Repetition accumulates.** Say "the CubeSat battery is an 18650
   lithium pack" across three conversations and three separate memories
   exist, all near-identical, all competing for the same handful of
   slots a brief carries. The store grows, and the *useful* fraction of
   what it surfaces shrinks.
2. **Corrections do not correct.** Say "actually we switched to
   LiFePO4" and both the old and new fact persist. Recency decides which
   surfaces, which means Zeni is one lucky retrieval away from
   confidently asserting something the user explicitly retracted — worse
   than not knowing, because it is wrong with authority.

Production memory systems answer this with an LLM reconciliation pass:
Mem0 compares each candidate fact against existing ones and emits
ADD / UPDATE / DELETE / NOOP. That is a model call per captured
statement, and — more importantly — it is a model deciding to **delete**
things the user said, where a wrong call silently destroys real memory.

## Decision

Add `runtime/memory/consolidation.py`: a `ConsolidationPolicy` seam on
the **write** side, mirroring `MemoryRetrievalPolicy` on the read side,
plus a `MemoryConsolidator` that every write path now goes through.

Three actions, decided before a memory is stored:

- **ADD** — genuinely new.
- **REINFORCE** — already known. The existing memory's importance rises
  by one (capped) and its `occurred_at` moves to now; no second memory
  is stored. Repetition becomes *evidence a fact matters* rather than
  clutter, which is the behavior a person would expect.
- **SUPERSEDE** — corrects something known. The old memory is deleted
  and the new one stored.

**`LexicalConsolidationPolicy` is deterministic, and asymmetric about
risk.** Reinforcing wrongly costs nothing — the fact survives, slightly
stronger. Superseding wrongly destroys a real memory. So the two use
different bars, and different *measures*:

- Reinforcement requires high **statement similarity** (Jaccard ≥ 0.85):
  is this the same thing said again?
- Supersession requires an explicit **correction marker** ("actually",
  "no longer", "we switched", "I meant") *and* moderate **subject
  overlap** (≥ 0.35). Never similarity alone.

The two-measure split was forced by implementation, not designed up
front: a correction *by definition* introduces words the original
lacked, and Jaccard charges the whole union for them, so "actually the
battery is LiFePO4 now" scored only 0.25 against the fact it corrects —
below any threshold safe to use. `subject_overlap` (the overlap
coefficient, shared words over the smaller vocabulary) asks the question
actually being posed — are these about the same thing — and is not
punished for the new statement saying something new.

**Semantic contradiction with no marker is deliberately not handled.**
"The battery is lithium" followed later by a flat "the battery is
LiFePO4" leaves both stored. Detecting that genuinely requires
semantics, and guessing at it with lexical rules would delete real
memories on coincidence. It is left for a model-assisted policy behind
this same seam — where the cost and the risk are opted into explicitly,
not paid by default.

**Pruning** (`MemoryConsolidator.prune`) deletes only memories meeting
*all four* criteria: not pinned, importance ≤ 4, never once recalled
(`access_count == 0`), and older than a threshold. Requiring all four is
what makes it safe to offer: anything deliberately committed, rated
important, or that has ever actually proven useful is out of reach by
construction. It is **never** automatic — exposed as `MemoryTool`'s
`prune`, itself behind `ConfirmationHook`, alongside `forget`.

`MemoryStore` gains `update` (emitting `MemoryUpdated`), the narrow
mutation reinforcement needs. Memories remain otherwise immutable.

## Consequences

- Repeating yourself now strengthens what Zeni knows instead of burying
  it, and an explicit correction actually corrects — verified end to end
  in `tests/test_memory_integration.py`, including that the superseded
  fact disappears from the brief.
- **Consolidation cannot be bypassed.** Every write goes through
  `MemoryConsolidator.store` rather than `MemoryStore.remember`, so a
  future writer added elsewhere inherits it rather than quietly
  reintroducing duplicates.
- The store stays a dumb persistence layer. Deciding what counts as a
  duplicate is policy, and putting it in the store would mean
  reimplementing it in every backend — including any future embedding
  one, where it would be tempting and wrong to fuse the two concerns.
- **Consolidation never fails a write.** A raising policy or a failing
  search falls back to storing the memory plainly: an unconsolidated
  memory is a far smaller problem than a lost one.
- Reinforcement moves `occurred_at`, so a repeatedly-restated fact reads
  as current rather than as of the first time it came up. This is
  correct for standing facts and slightly wrong for genuine events —
  acceptable, since `EVENT` memories are rarely restated verbatim.
- `subject_overlap` joins `similarity` in `matching.py` as a second
  lexical measure. Both are exported and independently useful; a future
  embedding backend would supply semantic versions of the same two
  questions.
