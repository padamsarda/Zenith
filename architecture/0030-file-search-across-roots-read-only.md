# 0030 — File search: many roots, read-only

- Status: Accepted
- Date: 2026-07-21

## Context

Three of the product vision's everyday examples — "search my notes for
MPPT", "find the latest datasheet", "open my CubeSat workspace" — do not
work, and cannot with what exists. `FilesystemTool` (ADR 0016) is
sandboxed to a single root, and `main.py` gives it `Path.cwd()`, so
Zeni can only see whichever folder it happened to be started from. Start
it from the Zenith repository and it can read Zenith, and nothing else a
person owns.

That sandbox is right for what `FilesystemTool` does. Its job is acting
*inside* a project — reading, writing, deleting — and a write tool that
could reach anywhere is exactly what a sandbox should prevent.

But "where is the thing I'm thinking of" is a different question, and it
has a different natural scope. Nobody keeps everything in one directory,
and a person asking Zeni to find a datasheet does not know or care which
folder it is under — that is the whole reason they are asking.

## Decision

Add `FileSearchTool` (`file_search`), searching several named roots,
with three operations: `name` (filename, wildcards supported), `content`
(text inside files), and `recent` (most recently modified, optionally
filtered).

**Read-only, by construction.** It has no operation that writes, moves,
renames, or deletes — finding is the entire contract. This is what makes
spanning several roots reasonable to allow at all, and is precisely why
it is *not* the same tool as `FilesystemTool`: broad reach and mutation
are each acceptable alone and dangerous together. It also follows that
`file_search` needs no `ConfirmationHook` gate (ADR 0025) while
`filesystem`'s `write`/`delete` do.

**Roots are the user's document folders, not the filesystem.**
`default_roots()` resolves home, Desktop, Documents, Downloads, and
OneDrive, keeping only those that exist. Searching `C:\` or `/` would be
slow, would surface system files nobody meant, and would give a tool
whose only boundary is its root list an unnecessarily large one. A
deployment with project folders elsewhere names them explicitly.

**Bounded on both axes.** Directories like `node_modules`, `.git`,
`__pycache__`, `AppData`, and every dotted directory are pruned during
the walk (using `os.walk` rather than `Path.rglob` precisely because
only the former allows pruning), and the walk stops after
`max_scanned` files. Content search reads only known text extensions and
skips oversized files. A search over a real home directory has to stay
predictable, or the tool is unusable in the one place it matters.

**Unreadable files are skipped, never raised.** Permission errors, locked
files, and mis-detected encodings are all normal on a real filesystem; a
search that aborts on the first awkward file is useless.

## Consequences

- The vision's file-finding examples work, and `filesystem` keeps its
  narrow sandbox rather than being widened to cover them — the outcome
  that would have been actively worse, since it would have given a
  delete-capable tool machine-wide reach.
- Two building bugs are worth recording, both caught by tests. Passing
  an explicitly empty root mapping fell back to the defaults, because
  `roots or default_roots()` treats `{}` as absent — meaning a caller
  asking for *no* roots silently got the user's entire home directory.
  It now checks `is None`. Separately, joining a root name to an
  OS-separated tail rendered paths as `work/notes\file.md`; results are
  now POSIX-separated throughout.
- Search is linear and uncached. Fine at the scale of a home directory
  with the pruning above, and the wrong approach if this ever needs to
  be fast over hundreds of thousands of files — an index would be a new
  backend, not a change to this tool's contract.
- Content search is substring, not regex, and reports the first matching
  line per file. Regex would be a natural additive extension; it is not
  built because no example in the vision needs it.
- Nothing yet *acts* on what is found: "move these files", "rename this
  folder", and "open my CubeSat workspace" still need either
  `FilesystemTool` pointed at the right root or a new tool. That gap is
  deliberate — mutation across arbitrary roots is exactly what this ADR
  declines to build, and doing it properly means deciding how a
  destination root gets authorized, not just widening a sandbox.
