# 0018 — SQLite-backed durable conversations

- Status: Accepted
- Date: 2026-07-21

## Context

`docs/assistant.md` listed this as a deliberate deferral since the
milestone that shipped conversations: "`ConversationStore` is in-memory.
Persistence is a store implementation behind the same interface; the
Engineering Manager's SQLite store (ADR 0004) is the proven pattern to
copy. Briefs are already assembled from durable state (ADR 0010's
principle), so nothing else changes." The roadmap named it directly:
"Durable conversations... Worth an ADR when it lands: whether both
applications share one database file."

Until now, `ConversationStore` was a single concrete class — the
in-memory implementation — not an abstraction with more than one
backend behind it. `ApplicationContext.conversations` held it via
`field(default_factory=ConversationStore)`, and every caller
(`AssistantEngine`, `ConsoleInterface`, `ToolCallRunner`) called it
directly. "Behind the same interface" required there to *be* an
interface — until a second implementation exists, "the interface" is
just whatever one class happens to expose.

## Decision

**`ConversationStore` becomes an ABC** (`runtime/conversation/store.py`):
the same six methods it already had (`create`, `get`, `has`, `list`,
`append`, `archive`), now abstract. The former concrete class moves,
unchanged in behavior, to `InMemoryConversationStore`
(`runtime/conversation/in_memory_store.py`) — the exact shape ADR
0011/0015's `AssistantProvider`/`EchoProvider` split and ADR 0005/ADR
0014's `Provider`/`InMemoryProvider` split already established
elsewhere in this repository for "one contract, a harmless default
implementation, a real one behind the same shape."
`ApplicationContext.conversations` now defaults to
`InMemoryConversationStore()` — behaviorally identical to before this
ADR, since it's the same code under a new name.

**`SQLiteConversationStore`** (`runtime/conversation/sqlite/`) is the
durable implementation, structured as a three-way split —
`database.py` (connection + `user_version` migrations), `serialization.py`
(row <-> domain conversion), `store.py` (the store class) — copying
`engineering_manager/store/`'s layout file-for-file, per the roadmap's
own instruction to copy the proven pattern. Two tables: `conversations`
and `messages` (a foreign key to it), metadata stored as JSON text,
enums by `.name`, timestamps as ISO-8601 — the same conventions ADR
0004 established. **Not shared code with `engineering_manager/store/`**:
the two are structurally identical but independently owned, matching
ADR 0002's boundary (`engineering_manager/` and `runtime/` never import
each other) and this repository's habit of waiting for real, proven
pain before extracting a shared abstraction (ADR 0005, ADR 0011, ADR
0013 all frame a *second* consumer as the pressure test, not a reason
to pre-share). If a third SQLite-backed store appears, or the
duplication becomes a real maintenance cost, that is the moment to
extract a shared connection/migration helper into `shared/` — not
before.

**Validation and lifecycle rules are not reimplemented.** `append` and
`archive` call `get` to reconstruct the `Conversation`, then run the
ordinary `Conversation.append`/`transition_to` on it — the same
`ConversationValidationError` / `ConversationNotFoundError` paths the
in-memory store already used — and only persist a row if that succeeds.
This means a durable and an in-memory store reject exactly the same
appends and transitions, because they are, literally, the same method
calls on the same domain class (ADR 0004's principle: "the domain layer
knows nothing about persistence," extended here to "and doesn't get a
second implementation of its own rules either").

**`Conversation.restore(...)`** is the new classmethod
(`runtime/conversation/conversation.py`) a store uses to rebuild a
`Conversation` from stored fields — `conversation_id`, `created_at`,
`title`, `metadata`, `state`, `messages` — bypassing the checks real
construction and appending enforce (a fresh `Conversation` always
starts `ACTIVE` with no messages; restoring an archived conversation's
already-valid history is not re-deciding whether it was valid).

**Not auto-wired.** `Runtime.start()` is unchanged; `ApplicationContext.conversations`
still defaults to the in-memory store. An integrator who wants durable
history assigns `SQLiteConversationStore(path)` onto `context.conversations`
directly — the same pattern `ClaudeProvider` (ADR 0015) and every
`runtime.tools` tool (ADR 0016) already follow: a fresh `python main.py`
gains no new capability it wasn't explicitly given. No config flag was
added for this; deployment code, not a config toggle, is where a
concrete store choice belongs, matching those two precedents.

**One database file, not shared with the Engineering Manager.** The
roadmap asked this question directly. The two applications' persistence
needs are unrelated in shape (conversation history vs. projects/plans/
tasks/sessions) and ADR 0002 forbids either from importing the other —
sharing a physical file would require a schema negotiation neither
domain needs, for no benefit neither currently has a use for. Revisit
only if a concrete need for cross-application queries appears.

## A bug this exposed, and the fix

Building `SQLiteConversationStore` and testing it against the real
assistant pipeline (not just its own unit tests) surfaced a genuine bug
in `AssistantEngine.handle`: it fetched `conversation =
application_context.conversations.get(...)` once, before the turn loop,
and reused that reference for every `AssistantContextAssembler.assemble`
call across the whole request. This worked only because
`InMemoryConversationStore.get()` happens to return the same live,
shared-mutation object every call — `.append()` elsewhere in the same
store mutates that exact object, so the engine's stale reference
"happened" to see every later append. `SQLiteConversationStore.get()`
does not share that property: it reconstructs a fresh `Conversation`
from rows on every call, by design (ADR 0010's "assembled from durable
state... never cached" applied literally). Against it, the engine's
cached reference went stale the moment the first user message was
recorded, and the second turn's brief was built from a `Conversation`
that still had zero messages — `EchoProvider needs at least one user
message`, even though the message really had been persisted.

The fix (`runtime/assistant/engine.py`): re-fetch `conversation` inside
the turn loop, immediately before each `assemble` call, instead of once
before it. This is not a workaround specific to SQLite — it makes the
engine's behavior match what ADR 0010 already claimed for every backend,
and costs one extra dictionary lookup per turn against the in-memory
store. `ToolCallRunner` never had this bug: it always appends by
conversation ID, through the store, and never holds a `Conversation`
reference across calls.

This is the second-implementation pressure test this repository's own
ADRs keep describing (0005, 0011, 0013) working exactly as advertised:
a contract that only one implementation had ever exercised looked
correct, and wasn't, until a structurally different second one forced
the assumption into the open. `tests/test_assistant_engine.py::test_second_turn_brief_includes_the_tool_result_with_a_reconstructing_store`
pins the fix — it fails against the pre-fix engine and passes after.

## Consequences

- `ConversationStore` joins `AssistantProvider`/`Provider` as a third
  contract in this repository with more than one implementation behind
  it, each swapped by assignment rather than a registry (the same shape
  `PermissionPolicy` already used) — there is exactly one active
  `ConversationStore` at a time, unlike providers or tools, so no
  registry was needed.
- The `AssistantEngine` fix applies to every current and future
  `ConversationStore` implementation, not just this one; any interface
  written the same way in the future (fetch once, mutate elsewhere,
  assume the reference stays live) should be treated as suspect until a
  second, non-shared-reference implementation exercises it.
- `runtime/exceptions.py` gained `ConversationStoreError`, mirroring the
  Engineering Manager's `StoreError`, for failures that are neither
  "not found" nor "invalid" — a newer-than-supported schema, a migration
  failure, or a wrapped `sqlite3.Error`.
- Zero behavior change to a default `python main.py` run: the default
  store, its class name change aside, is the same code it always was.
