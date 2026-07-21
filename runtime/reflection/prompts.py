"""The instructions each level of reflection is performed under.

Kept in one module, separate from the code that runs them, because these
are the part most likely to need tuning from experience — and tuning a
prompt should not mean editing control flow. Each is deterministic for a
given input, the same property ADR 0010 requires of skill instructions,
so a reflection can be reproduced from the memories that produced it.
"""

from __future__ import annotations

from collections.abc import Sequence

from runtime.memory.memory import Memory
from runtime.memory.recall import describe_age
from datetime import datetime

# Level one. Deliberately narrow: extract what was established, not what
# it means. Deep interpretation from a single conversation is where a
# model most reliably invents things, and it is also unnecessary — the
# scheduled pass sees far more evidence and is the right place for it
# (ADR 0029).
SESSION_INSTRUCTIONS = """\
You are reviewing one finished conversation with the user, to write down \
what is worth carrying forward.

Summarize concisely, covering only what the conversation actually \
established:
- what the user worked on or discussed
- decisions reached, and what they were
- preferences the user expressed
- tasks left unfinished or explicitly deferred

Rules:
- Report only what is supported by the material. Do not speculate about \
motives, feelings, or character.
- If nothing durable came up, reply with exactly: NOTHING
- Be brief. A few sentences, or a short list. No preamble.\
"""

# Level two. This is where interpretation is wanted — but grounded, and
# explicitly permitted to find nothing rather than manufacture a pattern
# from thin evidence.
DEEP_INSTRUCTIONS = """\
You are reviewing an accumulated body of things you know about the user, \
to understand them better than any single memory shows.

Identify what genuinely recurs across this material:
- recurring themes and subjects they return to
- longer-term goals and what they appear to be working toward
- habits and working patterns
- interests
- unfinished work still outstanding
- how their priorities appear to be shifting over time

Rules:
- Ground every observation in the material. A pattern needs several \
supporting memories, not one.
- Prefer fewer, well-supported observations over many thin ones. It is \
better to notice three real things than to list ten guesses.
- Say plainly when the evidence is thin, rather than overstating.
- Do not speculate about personality, mental state, or anything personal \
the user has not themselves expressed.
- If there is not enough here to see any real pattern, reply with \
exactly: NOTHING
- Write for the user to read about themselves. Direct, concrete, no \
preamble.\
"""

# Level three. The user asked a specific question, so the answer is
# shaped by that question rather than by a fixed template.
ON_DEMAND_TEMPLATE = """\
You are answering a question the user asked about what you know of them, \
using the material below.

Their question: {question}

Rules:
- Answer from the material. Ground what you say in it.
- If the material does not support an answer, say so plainly rather than \
filling the gap.
- Do not speculate about personality or mental state.
- Direct and concrete. No preamble.\
"""

NOTHING_MARKER = "NOTHING"


def render_memories(memories: Sequence[Memory], now: datetime) -> str:
    """Render `memories` as the material a reflection is performed over.

    Each line carries how long ago it happened and how important it was
    judged, since both change what a pattern across them means — the
    same fact recurring over months differs from it being said twice
    yesterday.
    """
    lines = []
    for memory in memories:
        age = describe_age(memory.occurred_at, now)
        marker = " [pinned]" if memory.pinned else ""
        lines.append(
            f"- ({age}, {memory.kind.name.lower()}, importance {memory.importance}"
            f"{marker}) {memory.content}"
        )
    return "\n".join(lines)


def on_demand_instructions(question: str) -> str:
    """Build the instructions for an on-demand reflection answering `question`."""
    return ON_DEMAND_TEMPLATE.format(question=question.strip())
