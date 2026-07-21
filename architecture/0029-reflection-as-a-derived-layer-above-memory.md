# 0029 — Reflection: three levels, as a derived layer above memory

- Status: Accepted
- Date: 2026-07-21

## Context

ADR 0027 and 0028 gave Zeni memory that records and maintains itself.
What neither gives it is *understanding*: memory can answer "what did I
say about the battery", never "what am I actually working on", "what
patterns do you see", or "what should I focus on next". Those are
questions no single stored memory answers, because the answer is in the
shape of many of them together.

This is the half of the memory literature left unbuilt. Stanford's
Generative Agents pair the memory stream with **reflection** —
periodically synthesizing clusters of memories into higher-level
inferences, which then become retrievable themselves. That is what
separates an assistant that recalls from one that understands.

Unlike everything shipped so far, this genuinely requires model calls:
no rule finds "you keep returning to power-subsystem work". So the
question is not whether to use a model but *when*, and what happens to
the raw record when a model starts producing derived content about it.

## Decision

Add `runtime/reflection/`, a layer **above** `runtime/memory/`, at three
levels, with a hard separation from raw memory.

### The separation, first

**Reflections never touch memories.** They are a separate domain type in
a separate store, in a separate database file. Reflection only ever
*reads* memories and writes something new alongside. Raw memories stay
immutable, exactly as ADR 0027 made them.

This is the load-bearing decision, and the reason for every structural
choice below. A model summarizing your month will sometimes be wrong.
If reflections could edit or replace memories, a wrong inference would
corrupt the evidence — and "what did I actually tell you" would stop
being answerable. Keeping them separate makes a bad reflection a
recoverable mistake: delete it, and everything it was drawn from is
still there, unaltered.

**Every reflection carries provenance.** `source_memory_ids` records the
memories an insight was derived from, in order, in a dedicated
`reflection_sources` table (a real many-to-many relation, so "which
insights came from this memory" is a query rather than a scan). "Why
does Zeni think this about me" is always answerable by looking them up
rather than trusting the sentence.

Provenance deliberately has **no foreign key** to memories. Reflections
live in their own database and must not depend on a memory row still
existing; a pruned memory leaves its ID behind as an honest record of
what the insight was drawn from at the time, rather than silently
rewriting history.

**Deep reflections are versioned, never overwritten.** Each new one is
stored as the next `generation`, pointing at the one it `supersedes`.
The whole series stays readable, so how Zeni's understanding evolved is
itself inspectable.

### The three levels

| Level | Trigger | Reads | Cost |
|---|---|---|---|
| `SESSION` | `ConversationArchived` | That conversation's memories | One cheap call, only for substantial conversations |
| `DEEP` | Due by interval, checked at startup | Everything accumulated | One call per interval |
| `ON_DEMAND` | `ReflectionTool` | Memories relevant to the question | One call, user-initiated |

**Level one is deliberately shallow.** Its prompt extracts what a
conversation *established* — decisions, preferences, unfinished work —
and explicitly forbids interpretation. Deep inference from a single
conversation is where a model most reliably invents things, and it is
also unnecessary: level two sees far more evidence and is the right
place for it.

**Thresholds keep it from firing on nothing.** A conversation needs at
least 3 captured memories before it is worth a call ("meaningful
conversations, not every chat"), and deep reflection needs at least 15
accumulated — a "pattern" across three data points is manufactured, not
found. Both are constructor arguments.

**Every prompt permits finding nothing.** Each instructs the model to
reply `NOTHING` when the material does not support a conclusion, and
`Reflector.reflect` returns `None` for it. Without this, every scheduled
run manufactures an insight, which is exactly how a reflection layer
becomes noise. Quality over frequency, as the requirement states.

### Structure

- **`Reflector`** is an ABC over "memories in, text out" — storage-
  independent by construction, and the reason every other part of the
  layer is testable with a stub and no model at all.
- **`ProviderReflector`** implements it through the existing
  `AssistantProvider` contract (ADR 0011) rather than inventing a second
  path to a model: a reflection is one turn, with instructions and
  material, producing text. No tools in its catalog — reflection reads
  and concludes, and must not be able to act. The provider is injected,
  so a deployment can point reflection at a cheaper model than it talks
  to; reflection runs unattended and its latency is invisible, which is
  exactly when that is worth doing.
- **`ReflectionService`** owns all three triggers, because they differ
  only in when they fire and what they read — the machinery beneath is
  identical, and three copies would drift.
- Prompts live in their own module: they are the part most likely to
  need tuning from experience, and tuning one should not mean editing
  control flow.

### Wiring

Session reflection subscribes to `ConversationArchived` on the event
bus, so no interface knows reflection exists and `ConsoleInterface`
keeps owning nothing but line I/O (ADR 0012). Deep reflection is checked
once at startup in `main.py`. On-demand needs no wiring — it is
`ReflectionTool`, registered with the rest of the suite.

## Consequences

- Zeni can now answer questions about itself-about-you that no stored
  memory contains, with every answer traceable to the memories that
  produced it.
- **Startup is the deep-reflection trigger, and that is a real
  limitation.** The runtime has no scheduler (ADR 0007), and for
  something started daily this approximates "every day or few days"
  closely enough to be honest about. A long-running deployment that
  never restarts would never reflect deeply; it needs a real trigger,
  which is a scheduler decision this ADR does not make.
- **Reflection is best-effort everywhere.** A failing reflector, an
  unreachable provider, or a raising service degrades to "no
  reflection": archiving a conversation still succeeds, startup still
  completes, the request still returns. Reflection is derived, optional
  value on top of a system that works without it, and must never be able
  to break the thing that triggered it.
- **Reflections are not yet recalled into briefs.** They are readable
  through `ReflectionTool` (`list`, which makes no model call, and is
  often enough), but the assembler does not inject them the way it
  injects memories. Doing so is a natural next step and a genuine design
  question — a stale deep reflection competing with fresh memories for
  brief space could easily make things worse, so it is deferred rather
  than assumed.
- `ApplicationContext` gains `reflections`, defaulting to
  `InMemoryReflectionStore`. Losing reflections on restart is less
  damaging than losing memories, since they are regenerable from the
  memories beneath them — which is itself a consequence of the
  separation this ADR is built on.
