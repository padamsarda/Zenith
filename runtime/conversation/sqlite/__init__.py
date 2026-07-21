"""SQLite-backed ConversationStore: connection, schema, and serialization.

Mirrors `engineering_manager/store/`'s three-way split
(`database.py`/`serialization.py`/`store.py`) — the pattern ADR 0004
proved for durable, transactional, dependency-free state, applied here
to conversation history (ADR 0018).
"""

from __future__ import annotations
