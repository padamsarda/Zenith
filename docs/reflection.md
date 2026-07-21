# Reflection

How Zeni turns what it remembers into what it understands. Memory
answers "what did I say about the battery"; reflection answers "what am
I actually working on", "what patterns do you see", "what should I focus
on next" — questions no single memory contains, because the answer is in
the shape of many together.

For why it is built this way, see
[ADR 0029](../architecture/0029-reflection-as-a-derived-layer-above-memory.md).
For the memory layer beneath it, [`memory.md`](memory.md).

## The separation from memory

**Reflections never touch memories.** They are a separate type, in a
separate store, in a separate database file. Reflection only reads
memories and writes something new alongside; raw memories stay
immutable.

This is the foundation everything else rests on. A model summarizing
your month will sometimes be wrong. If reflections could edit memories,
a wrong inference would corrupt the evidence, and "what did I actually
tell you" would stop being answerable. Kept separate, a bad reflection
is recoverable: delete it, and everything it came from is still there.

## The three levels

| Level | Trigger | Reads | When it costs a model call |
|---|---|---|---|
| `SESSION` | A conversation was archived | That conversation's memories | Only if it produced ≥ 3 memories |
| `DEEP` | Interval elapsed, checked at startup | Everything accumulated (≤ 300) | Only if ≥ 15 memories exist and it is due |
| `ON_DEMAND` | `ReflectionTool`'s `reflect` | Memories relevant to the question | Whenever asked |

### Level one — session

Runs when a conversation is archived, via a `ConversationArchived`
subscription, so no interface knows reflection exists.

Deliberately shallow: it extracts what the conversation *established* —
decisions, preferences, unfinished work — and its prompt explicitly
forbids interpretation. Deep inference from one conversation is where a
model most reliably invents things, and it is unnecessary anyway, since
level two sees far more evidence.

The 3-memory threshold is what makes this "meaningful conversations, not
every chat". "Open Spotify, thanks" captures nothing and triggers
nothing.

### Level two — deep

Synthesizes across everything accumulated: recurring themes, long-term
goals, habits, interests, unfinished work, shifting priorities.

**Versioned, never overwritten.** Each run is stored as the next
`generation`, pointing at the one it `supersedes`. The whole series
stays readable, so how Zeni's understanding evolved is itself
inspectable.

**Triggered at startup**, since the runtime has no scheduler (ADR 0007).
For something started daily this approximates "every day or few days"
well enough — but a deployment that never restarts would never reflect
deeply. That is a real limitation, not a hidden one.

### Level three — on demand

`ReflectionTool`'s `reflect` operation, for when the user asks directly.
The question selects the material through ordinary memory search, so
"what did I decide about the battery" reads narrowly while "what
patterns do you see" reads broadly (falling back to recent memories when
a broad question matches nothing lexically).

`list` reads conclusions already drawn and makes **no model call** —
often enough, and much cheaper.

## Reflection

`runtime/reflection/reflection.py`:

| Field | Type | Description |
|---|---|---|
| `content` | `str` | The insight. |
| `kind` | `ReflectionKind` | `SESSION`, `DEEP`, or `ON_DEMAND`. |
| `source_memory_ids` | `tuple[UUID, ...]` | **Provenance** — what this was drawn from, in order. |
| `generation` | `int` | Which version in the series. |
| `supersedes` | `UUID \| None` | The reflection this replaces. |
| `model` | `str \| None` | What produced it. |
| `metadata` | `dict` | e.g. the question asked, for `ON_DEMAND`. |
| `created_at` | `datetime` | When it was drawn. |

### Provenance

Every insight records the memories it came from, so "why does Zeni think
this" is answerable by looking them up rather than trusting the
sentence:

```python
reflection = context.reflections.latest(ReflectionKind.DEEP)
for memory_id in reflection.source_memory_ids:
    print(context.memory.get(memory_id).content)
```

Stored in a dedicated `reflection_sources` table — a real many-to-many
relation, so "which insights came from this memory" is a query, not a
scan.

Deliberately **no foreign key** to memories. Reflections live in their
own database and must not depend on a memory still existing; a pruned
memory leaves its ID behind as an honest record of what the insight was
drawn from at the time, rather than silently rewriting history.

## ReflectionStore

```python
store.add(reflection, context)      # -> Reflection, emits ReflectionCreated
store.get(reflection_id)            # -> Reflection, raises ReflectionNotFoundError
store.delete(reflection_id, context)  # emits ReflectionDeleted
store.list(kind=..., limit=...)     # newest first
store.latest(kind)                  # -> Reflection | None
```

- **`InMemoryReflectionStore`** — the default. Losing reflections on
  restart is less damaging than losing memories: they are derived and
  regenerable from what is beneath them.
- **`SQLiteReflectionStore`** — durable, at `~/.zenith/reflections.db`.
  A *separate file* from memory, so rebuilding the derived layer can
  never put the raw one at risk.

Both run the same parametrized tests.

## Reflector

The only part needing a model, isolated behind an ABC over "memories in,
text out" — which is why everything else is testable with a stub and no
model at all.

```python
class Reflector(ABC):
    def reflect(self, memories, instructions, *, now=None) -> str | None: ...
```

`ProviderReflector` implements it through the existing
`AssistantProvider` contract (ADR 0011): one turn, instructions plus
material, text out. **No tools in its catalog** — reflection reads and
concludes, and must not be able to act.

The provider is injected, so reflection can use a cheaper model than
conversation does. It runs unattended and its latency is invisible,
which is exactly when that is worth doing:

```python
ReflectionService(ProviderReflector(cheap_provider, model="claude-haiku-4-5"))
```

### Finding nothing is a valid outcome

Every prompt instructs the model to reply `NOTHING` when the material
does not support a conclusion, and `reflect` returns `None` for it.
Without this, every scheduled run manufactures an insight — which is
exactly how a reflection layer turns into noise. **Quality over
frequency.**

## Configuration

Constructor arguments on `ReflectionService`:

| Argument | Default | Meaning |
|---|---|---|
| `min_session_memories` | 3 | Below this, a conversation is not worth reflecting on. |
| `min_deep_memories` | 15 | Below this, there is not enough for a real pattern. |
| `deep_interval_hours` | 24 | How long between deep reflections. |
| `deep_memory_limit` | 300 | How many memories a deep reflection reads. |
| `on_demand_limit` | 60 | How many an on-demand reflection reads. |

## Events

All with `source="reflection_store"`:

- `ReflectionCreated` — `reflection_id`, `kind`, `generation`, `sources`.
- `ReflectionDeleted` — `reflection_id`.
- `ReflectionSkipped` — `kind`, `reason`. Emitted rather than staying
  silent, because "nothing happened" and "nothing was worth reflecting
  on" are different states and only one indicates a problem.

## Failure behavior

Reflection never breaks what triggered it. A failing reflector, an
unreachable provider, or a raising service degrades to "no reflection":
archiving still succeeds, startup still completes, the request still
returns. It is derived, optional value on top of a system that works
without it.

## Known limitations

- **Reflections are not recalled into briefs.** They are readable via
  `ReflectionTool`, but the assembler does not inject them the way it
  injects memories. A stale deep reflection competing with fresh
  memories for brief space could easily make things worse, so this is
  deferred rather than assumed.
- **Deep reflection triggers at startup only.** A deployment that never
  restarts never reflects deeply.
- **No cross-linking between reflections and derived semantic
  memories.** Reflections reference memories; nothing yet references
  reflections.

## Extending

| To… | Do this |
|---|---|
| Use a different/cheaper model | Construct `ProviderReflector` with another provider. |
| Change what reflection asks for | Edit `runtime/reflection/prompts.py`. |
| Reflect without a model | Subclass `Reflector`. |
| Change when levels fire | Constructor arguments on `ReflectionService`, or call its methods directly. |
| Store reflections elsewhere | Implement `ReflectionStore`. |
