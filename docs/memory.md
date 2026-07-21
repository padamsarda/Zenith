# Memory

How Zeni remembers things, and how it decides what to recall. This
document covers the memory model, the storage contract, retrieval
scoring, temporal resolution, and how memory reaches a conversation
without anyone asking it to.

For why it is built this way — and what was surveyed first — see
[ADR 0027](../architecture/0027-memory-automatic-recall-recency-importance-relevance.md).

## Overview

```
user says something
  -> MemoryCaptureHook      after_request: is this worth keeping?
       └─ salience rules     skip trivia, classify, weight, pin
  -> MemoryConsolidator      new, a repeat, or a correction?
       └─ ConsolidationPolicy   ADD / REINFORCE / SUPERSEDE
  -> MemoryStore             durable, announced on the EventBus

user asks something
  -> AssistantContextAssembler   composing the brief, every turn
       └─ MemoryRecaller
            ├─ parse_temporal_query   "yesterday" -> absolute window + subject
            ├─ MemoryStore.search     candidates + relevance (FTS5/BM25)
            └─ MemoryRetrievalPolicy  recency + importance + relevance
  -> TurnBrief.instructions   "[What you remember] ..."
```

Recall is **automatic**. Nothing the model does triggers it; by the time
a provider produces a turn, what Zeni knows is already in the brief.

## Memory

`runtime/memory/memory.py`. A frozen dataclass:

| Field | Type | Description |
|---|---|---|
| `content` | `str` | What is remembered, in words. |
| `kind` | `MemoryKind` | `FACT`, `PREFERENCE`, `DECISION`, `EVENT`, or `TASK`. |
| `importance` | `int` | 1–10. How much it deserves to be recalled. |
| `pinned` | `bool` | Explicitly committed; never decays out of reach. |
| `tags` | `tuple[str, ...]` | Optional labels. |
| `source` | `str` | Where it came from (`conversation`, `tool`, …). |
| `metadata` | `dict[str, Any]` | Extension point. |
| `occurred_at` | `datetime` | **When the thing happened.** |
| `created_at` | `datetime` | **When it was written down.** |
| `last_accessed_at` | `datetime` | Last recall; drives recency. |
| `access_count` | `int` | How often it has been recalled. |
| `memory_id` | `UUID` | Unique per memory. |

**`occurred_at` and `created_at` are deliberately separate.** They
differ whenever something is recorded after the fact, and conflating
them mis-answers every relative-time question — the single
highest-impact detail in the benchmark literature this design follows.

Memories are immutable apart from `last_accessed_at`/`access_count`,
which the store updates on recall. A correction is a new memory, or a
`forget`.

## MemoryStore

`context.memory` is the only path that stores, searches, or deletes.

```python
store.remember(memory, context)    # -> Memory, emits MemoryRemembered
store.get(memory_id)               # -> Memory, raises MemoryNotFoundError
store.has(memory_id)               # -> bool
store.update(memory, context)      # replace by ID, emits MemoryUpdated
store.forget(memory_id, context)   # emits MemoryForgotten
store.search(query, window=..., limit=...)   # -> tuple[MemoryCandidate, ...]
store.touch(memories, context)     # record a recall
store.list()                       # -> list[Memory], newest first
```

Write through `MemoryConsolidator.store`, not `remember` directly — see
[Consolidation](#consolidation) below. `update` exists for the narrow
mutation reinforcement needs; memories are otherwise immutable.

Two implementations (mirroring `ConversationStore`, ADR 0018):

- **`InMemoryMemoryStore`** — `context.memory`'s default. Nothing
  survives a restart, which is the opposite of what memory is for;
  honest scaffolding, same role `EchoProvider` plays for providers.
- **`SQLiteMemoryStore`** (`runtime/memory/sqlite/`) — the durable one.
  Not auto-wired: an integrator assigns it, as `main.py` does at
  `~/.zenith/memory.db`.

Both are driven through the same parametrized tests
(`tests/test_memory_store.py`), because an in-memory store that behaves
differently from the durable one is a misleading test double.

`search` is the one method that genuinely differs between backends,
because matching text is backend-specific. It returns
`MemoryCandidate`s carrying a **normalized relevance in `[0, 1]`**;
combining that with recency and importance is the retrieval policy's
job, identical everywhere.

### Why FTS5, not embeddings

`SQLiteMemoryStore` ranks with SQLite's built-in FTS5/BM25. FTS5 ships
compiled into CPython's bundled SQLite, so this costs no dependency, no
credential, and no second vendor — which the standard-library-only
convention requires.

The tradeoff is real and worth knowing: **BM25 matches names,
identifiers, and exact terms well, and misses synonyms.** Asking about
"the power system" will not retrieve a memory that only says "battery".
Phrasing a question with the words the fact was stated in works best.

Replacing it is a new `MemoryStore`, not a redesign: scoring is
backend-agnostic by construction.

## Retrieval

`runtime/memory/retrieval.py`.

```
score = w_recency · recency + w_importance · importance + w_relevance · relevance
```

| Term | How | Default weight |
|---|---|---|
| recency | `0.5 ** (hours_since_access / half_life)`, 72h half-life | 1.0 |
| importance | `importance / 10` | 1.0 |
| relevance | Normalized BM25 from the store | **2.0** |

Relevance is weighted highest on purpose: what was actually asked should
outrank what is merely recent or merely important.

**Pinned memories floor their recency at 0.6.** Without it, a
months-old pinned fact would need an overwhelming relevance match to
resurface — exactly what reads as "it forgot what I told it to
remember".

`ScoredMemory` keeps the three components alongside the total, so a
recall can be explained rather than only trusted.

Swap the whole thing by subclassing `MemoryRetrievalPolicy`; the store,
recaller, and assembler need no changes.

## Time

`runtime/memory/temporal.py`. `parse_temporal_query(text, now)` returns
a `TemporalQuery` with two parts:

- **`window`** — an absolute `TimeWindow`, or `None` for no constraint.
- **`subject`** — the query **with the time phrase removed**.

Both halves matter. Resolving "yesterday" to absolute timestamps is what
makes it mean the right day tomorrow; *stripping* it is what stops the
lexical search from hunting for memories containing the literal word
"yesterday", which matches nothing.

Understood: `yesterday`, `day before yesterday`, `today`/`this morning`,
`N days/weeks/months/years ago`, `last/past N days/weeks/months`,
weekday names (most recent occurrence), and month names (most recent
occurrence — memory only looks backward, so in July "October" means last
year's).

Unrecognized phrasing yields `None`, meaning "no time constraint" — never
"no matches". An unparsed phrase must never narrow a search to nothing.

When a window is present but nothing in it matches lexically,
`MemoryRecaller` falls back to the window alone: a question that named a
period deserves an answer about that period.

## Salience — what gets remembered

`runtime/memory/salience.py`, applied by `MemoryCaptureHook`
(`runtime/assistant/memory_capture.py`) after every **successful**
request.

**Skipped**: device commands (`open spotify`, `pause the music`, `turn
up the volume`), pleasantries, and anything under 12 characters. These
are re-derivable in a second and would bury everything else.

**Kept**, classified and weighted:

| Signal | Kind | Importance | Pinned |
|---|---|---|---|
| "remember that…", "don't forget", "from now on" | (inferred) | 10 | **yes** |
| "we decided", "we agreed", "settled on" | `DECISION` | 8 | no |
| "I prefer", "I always", "my favorite" | `PREFERENCE` | 7 | no |
| "I need to", "remind me", "next step" | `TASK` | 7 | no |
| anything else substantive | `FACT` | 5 | no |

An explicit marker always wins: "remember that I always open Spotify
after VS Code" is a preference about behavior, not a one-off command,
even though it is command-shaped.

Failed requests are never captured — the exchange did not happen as
intended, and recording it would record a misunderstanding.

### Limitations worth knowing

- **Capture is verbatim**, not summarized. Cheap, deterministic, and
  never wrong about what was said — but it does not rewrite statements
  into cleaner ones or synthesize higher-level insights across many
  memories.
- **Contradiction without a marker is not detected.** See
  [Consolidation](#consolidation): stating a replacement fact flatly,
  with no "actually" or "no longer", leaves both stored.

## Consolidation

`runtime/memory/consolidation.py`, ADR 0028. Applied to **every** write,
before it reaches the store, so automatic capture does not slowly fill
the store with near-duplicates and stale facts.

| Action | When | Effect |
|---|---|---|
| `ADD` | Genuinely new | Stored normally. |
| `REINFORCE` | Statement similarity ≥ 0.85 | No new memory. The existing one's importance rises by one (capped at 10) and its `occurred_at` moves to now. |
| `SUPERSEDE` | Explicit correction marker **and** subject overlap ≥ 0.35 | The old memory is deleted, the new one stored. |

So repeating yourself **strengthens** what Zeni knows rather than
cluttering it, and correcting yourself actually corrects.

**The two conditions use different measures on purpose.** Reinforcement
asks "is this the same statement?" (Jaccard `similarity`). Supersession
asks "is this about the same thing?" (`subject_overlap`, the overlap
coefficient). A correction by definition introduces new words, and
Jaccard charges the whole union for them — "actually the battery is
LiFePO4 now" scores only 0.25 against the fact it corrects, below any
safe threshold, while subject overlap scores 0.4.

**Deliberately asymmetric about risk.** Reinforcing wrongly costs
nothing; superseding wrongly destroys a real memory. So supersession
*never* fires on similarity alone — it requires an explicit correction
marker ("actually", "no longer", "we switched", "I meant", "scratch
that"). Two similar-but-different facts are always both kept.

**What this does not do:** semantic contradiction with no marker. "The
battery is lithium" followed by a flat "the battery is LiFePO4" leaves
both stored, with recency and importance deciding which surfaces.
Detecting that needs real semantics; guessing with lexical rules would
delete real memories on coincidence. A model-assisted
`ConsolidationPolicy` is the place for it.

Consolidation **never fails a write**: a raising policy or a failing
search falls back to storing the memory plainly, since an
unconsolidated memory is a far smaller problem than a lost one.

### Pruning

`MemoryConsolidator.prune` deletes a memory only when **all four** hold:

- not `pinned`,
- `importance` at or below a threshold (4 by default),
- `access_count == 0` — never once recalled,
- older than `older_than_days` (90 by default).

Requiring all four is what makes it safe to offer at all: anything
deliberately committed, rated important, or that has ever proven useful
is out of reach by construction.

**Never automatic.** Deleting memories is exactly the kind of thing that
must be asked for, so it runs only via `MemoryTool`'s `prune`, itself
behind `ConfirmationHook`.

## MemoryTool

`runtime/tools/memory_tool.py`, `tool_id="memory"`. **Not** how memory
normally reaches a conversation — recall is automatic. This covers what
automatic recall cannot:

| Operation | Purpose | Confirmed? |
|---|---|---|
| `remember` | Deliberately commit a fact. Pins and maxes importance by default. Goes through consolidation, so restating reinforces. | no |
| `search` | Look further back than the handful of entries in a brief. | no |
| `forget` | Delete something wrong, by `memory_id`. | **yes** |
| `prune` | Bulk-delete old, unused, unimportant, unpinned memories. | **yes** |

## Events

All with `source="memory_store"`:

- `MemoryRemembered` — `memory_id`, `kind`, `importance`, `pinned`.
- `MemoryUpdated` — `memory_id`, `importance`.
- `MemoryForgotten` — `memory_id`.
- `MemoriesRecalled` — `query`, `count`, `window`.

## Configuration

Nothing yet. Half-life, weights, and recall limits are constructor
arguments on `RecencyImportanceRelevancePolicy` and `MemoryRecaller`;
`main.py` uses the defaults. Promote them to `config.toml` if daily use
shows the defaults are wrong.

## Failure behavior

Memory never fails a request. `MemoryRecaller.recall` and
`MemoryCaptureHook.after_request` both catch, log, and continue, so a
broken store yields an assistant with no memory rather than a broken
assistant — the same rule ADR 0023 gives the Engineering Manager's
revision probe.

## Extending

| To… | Do this |
|---|---|
| Change what is recalled | Subclass `MemoryRetrievalPolicy`, pass to `MemoryRecaller`. |
| Change how repeats and corrections merge | Subclass `ConsolidationPolicy`, pass to `MemoryConsolidator`. |
| Change how text is matched (e.g. embeddings) | Implement `MemoryStore`; scoring is unaffected. |
| Change what is captured | Subclass `MemoryCaptureHook`, or replace the salience rules. |
| Understand a recall | Read `ScoredMemory`'s components, or subscribe to `MemoriesRecalled`. |
| Understand a merge | Read the returned `ConsolidationDecision` (action, matched memory, score). |
