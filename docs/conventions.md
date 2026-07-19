# Development Conventions

Conventions observed throughout this codebase. Follow these for any new
code in `runtime/`, `configs/`, `shared/`, or `engineering_manager/`.

## Language and style

- Python 3.12+. Every module starts with `from __future__ import annotations`.
- Type hints on every public function, method, and dataclass field.
- PEP 8 naming and layout.
- `pathlib.Path`, not `os.path`, for filesystem paths.
- No external dependencies beyond the standard library, except `pytest`
  as a dev-only dependency for testing. (`sqlite3`, `json`, `argparse`,
  etc. are standard library and fine.)
- Import boundaries (ADR 0002): `engineering_manager/` never imports
  `runtime/` or `configs/`; `runtime/` never imports
  `engineering_manager/`; `shared/` imports neither.

## Structure

- One responsibility per file. If a file is approaching ~250 lines,
  split it.
- Prefer composition over inheritance. The one deliberate exception is
  the `Event` base class, where subclassing adds no new fields and exists
  purely to give each event a distinct, self-documenting type.
- No module-level mutable globals. Shared state lives on
  `ApplicationContext` and is passed explicitly.
- No decorators, no metaclasses, no "magic" registration. Registration
  and subscription are explicit method calls (`ServiceRegistry.register`,
  `EventBus.subscribe`).

## Errors

- Every raised error is a subclass of `ZenithError`
  (`shared/exceptions.py`). Don't raise bare `ValueError`, `KeyError`,
  etc. from public APIs.
- Exceptions specific to a runtime subsystem (service registry, event
  bus, commands, plugins) live in `runtime/exceptions.py`, not
  `shared/exceptions.py` — `shared/` is reserved for exceptions with no
  dependency on the assistant runtime's own abstractions.
- Validation functions (`runtime/validation.py`) raise `ValidationError`
  rather than returning `False` — a successful call means the value has
  already been checked, so callers don't need to re-check it.
- Don't shadow built-in exception names; `ZenithRuntimeError`, not
  `RuntimeError`.

## Dataclasses

- Immutable data (`Config`, `Event` and its subclasses) uses
  `@dataclass(frozen=True)`.
- Mutable, long-lived state (`ApplicationContext`) uses a plain
  `@dataclass`.

## Docstrings

- Every public class and function has a docstring.
- One line if the name and signature already say everything; add `Args`/
  `Returns`/`Raises` sections when behavior isn't obvious from the
  signature.
- No docstring restates what the code already makes obvious; explain the
  non-obvious "why" in inline comments only, sparingly.

## Testing

- `pytest`, one test file per source module: `runtime/foo.py` ->
  `tests/test_foo.py`. Engineering Manager modules use a `test_em_`
  prefix (`engineering_manager/store/store.py` -> `tests/test_em_store.py`)
  so names never collide in the flat `tests/` directory.
- Test names read as a sentence describing the behavior under test:
  `test_<subject>_<expected_behavior>`.
- Use `tmp_path` for anything touching the filesystem; never write to the
  real project tree from a test.
- Each test creates its own `Runtime` / `ApplicationContext` / `EventBus`
  / `ServiceRegistry` instance — no shared mutable fixtures, so tests
  can't leak state into one another.

## Architecture decisions

- Any change that would make a future reader ask "why is it like this?"
  — a new subsystem, a layer boundary, a storage choice, a protocol
  contract, a dependency-policy change — gets an ADR in
  `architecture/`, following `architecture/README.md`.
- Never contradict an accepted ADR silently; supersede it with a new
  one.

## Commits

- One commit per completed milestone/sprint, made only when explicitly
  requested.
