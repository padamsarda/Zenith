"""Zeni's long-term memory: what it knows, and how it recalls it.

Structured as the same three-part split the rest of the runtime uses —
a domain object (`Memory`), a storage contract with an in-memory default
and a durable SQLite backend (`MemoryStore`), and a policy seam for the
one genuinely debatable decision (`MemoryRetrievalPolicy`: what to
recall, and in what order). See ADR 0027 for why retrieval scores
recency, importance, and relevance together, and `docs/memory.md` for
how the pieces fit.
"""

from __future__ import annotations
