"""Query tokenization and lexical relevance shared by memory backends.

`InMemoryMemoryStore` scores relevance with these directly; the SQLite
backend uses `tokenize` to build its FTS5 query and lets SQLite's own
BM25 do the ranking. Keeping tokenization in one place is what stops the
two backends from disagreeing about what counts as a word — a
disagreement that would make the in-memory store a misleading test
double for the durable one.
"""

from __future__ import annotations

import re

_WORD_PATTERN = re.compile(r"[a-z0-9]+")

# Words carrying no retrieval signal. Kept short on purpose: an
# aggressive stop list silently destroys real queries ("the plan" is not
# improved by dropping "plan"), and BM25 already down-weights terms that
# appear everywhere.
STOP_WORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "did", "do", "does",
        "for", "from", "had", "has", "have", "i", "if", "in", "is", "it", "its", "me",
        "my", "of", "on", "or", "our", "so", "that", "the", "their", "them", "then",
        "there", "these", "they", "this", "to", "was", "we", "were", "what", "when",
        "where", "which", "who", "will", "with", "you", "your",
    }
)


def tokenize(text: str, *, drop_stop_words: bool = True) -> tuple[str, ...]:
    """Split `text` into lowercase alphanumeric tokens.

    May legitimately return empty — for `""`, and for a query of nothing
    but stop words ("what was it about"). Callers must read that as "this
    query carries no retrieval signal" and rank on time and recency
    instead, which is the right answer for exactly those queries: they
    name a subject no more specifically than the conversation already
    has.
    """
    tokens = tuple(_WORD_PATTERN.findall(text.lower()))
    if not drop_stop_words:
        return tokens
    return tuple(token for token in tokens if token not in STOP_WORDS)


def overlap_relevance(query_tokens: tuple[str, ...], content: str) -> float:
    """Score `content` against `query_tokens` by proportion of terms matched.

    A deliberately simple lexical measure for the in-memory backend:
    what fraction of the query's distinct terms appear in the content,
    with a partial credit for prefix matches so "battery" still matches
    "batteries". Returns `0.0` for an empty query, which the caller reads
    as "rank on recency and importance alone".
    """
    if not query_tokens:
        return 0.0
    content_tokens = set(tokenize(content, drop_stop_words=False))
    if not content_tokens:
        return 0.0

    matched = 0.0
    for term in set(query_tokens):
        if term in content_tokens:
            matched += 1.0
        elif any(token.startswith(term) or term.startswith(token) for token in content_tokens):
            matched += 0.5
    return min(matched / len(set(query_tokens)), 1.0)


def similarity(left: str, right: str) -> float:
    """Score how alike two texts are, symmetrically, in `[0, 1]`.

    Jaccard overlap of their content words. Unlike `overlap_relevance`,
    which asks the directional question "does this content answer this
    query", this asks "are these two statements the same thing" — and
    that has to be symmetric, or whether two memories were judged
    duplicates would depend on which one happened to be written first.

    Two texts with no content words (only stop words) are treated as
    dissimilar rather than identical: there is no evidence they say the
    same thing, and merging on that basis would silently lose one.
    """
    left_tokens = set(tokenize(left))
    right_tokens = set(tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return intersection / union if union else 0.0


def subject_overlap(left: str, right: str) -> float:
    """Score whether two texts are *about* the same thing, in `[0, 1]`.

    The overlap coefficient — shared content words over the smaller of
    the two vocabularies — rather than `similarity`'s Jaccard. The
    distinction matters for corrections: "actually the battery is
    LiFePO4 now" and "the battery is an 18650 lithium pack" are clearly
    about the same subject, yet score only 0.25 by Jaccard, because a
    correction *by definition* introduces words the original lacked and
    Jaccard charges the whole union for them. Overlap asks the question
    actually being posed — do these concern the same thing — and is not
    punished for the new statement saying something new.
    """
    left_tokens = set(tokenize(left))
    right_tokens = set(tokenize(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))


def normalize_scores(raw: list[float]) -> list[float]:
    """Min-max normalize `raw` into `[0, 1]`.

    An all-equal set normalizes to 1.0 rather than 0.0: every candidate
    matched the query equally well, which is maximal agreement, not
    maximal irrelevance. Mapping it to 0 would let recency alone decide
    among equally good matches.
    """
    if not raw:
        return []
    lowest, highest = min(raw), max(raw)
    if highest == lowest:
        return [1.0] * len(raw)
    span = highest - lowest
    return [(value - lowest) / span for value in raw]
