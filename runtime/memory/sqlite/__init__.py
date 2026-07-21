"""The durable, SQLite-backed MemoryStore (ADR 0027).

Mirrors `runtime.conversation.sqlite` in shape: connection and
migrations in `database.py`, row conversion in `serialization.py`, and
the `MemoryStore` implementation itself in `store.py`.
"""

from __future__ import annotations
