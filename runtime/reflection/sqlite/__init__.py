"""The durable, SQLite-backed ReflectionStore (ADR 0029).

Mirrors `runtime.memory.sqlite` in shape: connection and migrations in
`database.py`, the `ReflectionStore` implementation in `store.py`.
Provenance lives in its own `reflection_sources` table, so "which
insights came from this memory" is a query rather than a scan.
"""

from __future__ import annotations
