# 0027 — Memory: automatic recall, scored by recency, importance, and relevance

- Status: Accepted
- Date: 2026-07-21

## Context

Memory is the product vision's other first-class feature, and the one
that makes the difference between a command interface and an assistant:
"continue yesterday's work", "what did we decide about the CubeSat
battery", answered without re-explaining anything. Nothing in the
runtime did this. Conversations are durable (ADR 0018), but a
conversation is a transcript — it answers "what was said in *this*
thread", never "what do you know about me", and it grows without bound
while getting no better at recall.

The requirements that shaped this, stated directly by the product owner:
recall must be **automatic** (if I ask something, it should already be
in context), it must understand **relative time** ("yesterday", "the day
before", "that month"), it must find the **closest match** rather than
requiring exact phrasing, trivia like opening an app must **not** be
stored ("they can just be searched again"), and an explicit "remember
this" must be **kept properly**.

Rather than invent a scheme, the established ones were surveyed. The
convergent findings:

- **Stanford's Generative Agents** established the retrieval score still
  used in most systems: `recency + importance + relevance`, with recency
  as exponential decay and importance as an explicit 1–10 rating. No
  single term suffices — recency alone forgets what matters, importance
  alone ignores the question, relevance alone surfaces stale trivia.
- **Mem0** contributes extract-then-reconcile: salient facts are
  distilled from conversation, then reconciled against existing memory
  (ADD/UPDATE/DELETE/NOOP) so it neither accumulates duplicates nor
  keeps contradictions.
- **Zep** leads temporal benchmarks through bi-temporal modeling —
  tracking when something *happened* separately from when it was
  *recorded*.
- **LongMemEval** isolates the highest-leverage detail: relative
  expressions must be resolved to **absolute** timestamps, and
  time-window filtering at query time improves temporal recall by
  7–11%.

Every one of those systems computes relevance with vector embeddings.
This repository is standard-library-only (`docs/conventions.md`), and
embeddings would mean both a new dependency and a second credential —
Anthropic's API has no embeddings endpoint, so it would also mean a
second vendor.

## Decision

Add `runtime/memory/`, structured like every other subsystem here: a
domain object, a storage contract with an in-memory default and a
durable SQLite backend, and a policy seam for the debatable part.

**`Memory` is bi-temporal.** `occurred_at` (when the thing happened) is
separate from `created_at` (when it was written down). This is what
makes "what did we decide yesterday" answerable at all; conflating them
mis-answers every relative-time question. `last_accessed_at` and
`access_count` are updated on recall, so recency reflects genuine use.

**Retrieval is `RecencyImportanceRelevancePolicy`** — the Stanford
formula, behind a `MemoryRetrievalPolicy` ABC of the same shape as
`PermissionPolicy` and the Engineering Manager's policy seams. Recency
decays exponentially (72h half-life by default). Relevance is weighted
highest (2.0 vs 1.0): what was actually asked should outrank what is
merely recent or merely important.

**Relevance is SQLite FTS5/BM25, not embeddings.** FTS5 ships compiled
into CPython's bundled SQLite, so full-text search with BM25 ranking
costs nothing — no dependency, no credential, no vendor. This is the
one place this design knowingly departs from every system surveyed, and
the tradeoff is real: BM25 matches names, identifiers, and exact terms
well, and misses synonyms ("battery" will not match "power system").
The seam is drawn so this is replaceable: `MemoryStore.search` returns
candidates carrying a normalized relevance in `[0, 1]`, and *scoring* is
backend-agnostic — an embedding or hybrid backend is a new `MemoryStore`
with no change to the policy, the recaller, or the assembler.

**Pinned memories have a recency floor.** An explicit "remember this"
sets `pinned`, whose recency term never decays below `0.6`. Without it a
months-old pinned fact would need an overwhelming relevance match just
to resurface — precisely what a user experiences as "it forgot what I
told it to remember".

**Relative time is resolved *and stripped*.** `parse_temporal_query`
converts "yesterday" into an absolute `TimeWindow` **and** removes the
phrase from the subject searched for. Building this surfaced why that
second half matters: leaving the phrase in makes the lexical search hunt
for memories literally containing the word "yesterday", which matches
nothing. When a window is given but nothing in it matches lexically,
recall falls back to the window itself — a question that named a period
deserves an answer about that period.

**Recall is automatic, in the assembler — not a tool.**
`AssistantContextAssembler` calls `MemoryRecaller` while composing every
brief, so relevant memories are present before the provider produces its
turn. This is the load-bearing decision: a memory *tool* would mean the
model must first think to look something up, spending a turn and
frequently not bothering. `MemoryTool` still exists, for the cases
automatic recall cannot cover — deliberately committing a fact,
searching further back than the handful of entries a brief carries, and
forgetting something wrong.

**Salience is explicit rules, not an LLM call.**
`runtime/memory/salience.py` decides what is worth storing: device
commands and pleasantries are skipped, decisions/preferences/tasks are
classified and weighted, and an explicit marker ("remember that…") pins
and maxes importance. Rules cost nothing per turn and are inspectable
and correctable by a human, where an LLM rating pass costs a call per
exchange. `MemoryCaptureHook` (an `after_request` hook) applies them,
storing the user's own words verbatim.

## Consequences

- Zeni now knows things across conversations and across restarts, with
  no tool call and no prompting — covered end to end in
  `tests/test_memory_integration.py`, including cross-conversation
  recall and survival across a simulated restart.
- **Verbatim capture, not summarization**, is the accepted limitation of
  this first version. A summary would read better and could merge
  related facts, but costs a provider call per exchange and can invent
  detail the user never said. Mem0's reconcile step (UPDATE/DELETE on
  contradiction) is therefore also absent: memories accumulate and can
  contradict each other, with recency and importance deciding which
  surfaces. Both are natural refinements behind the same hook.
- **Everything non-trivial the user says is stored.** That is what makes
  it work without being asked, and it means the store grows with use and
  holds whatever was said — including things said carelessly.
  `MemoryTool`'s `forget` is the correction path; pruning, expiry, and a
  review surface are not built.
- Memory failures degrade rather than propagate: `MemoryRecaller.recall`
  and `MemoryCaptureHook` both swallow and log, so a broken memory
  subsystem yields an assistant with no memory rather than a failed
  request (the rule ADR 0023 gives the Engineering Manager's revision
  probe, applied here).
- `ApplicationContext` gains `memory`, defaulting to
  `InMemoryMemoryStore`. `main.py` swaps in `SQLiteMemoryStore` at
  `~/.zenith/memory.db` — beside the Engineering Manager's database,
  deliberately not in the working directory, since memory that moved
  with the current folder would not be memory.
