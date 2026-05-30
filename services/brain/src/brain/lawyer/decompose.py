"""Decompose a draft customer-facing message into ATOMIC claims.

The Critic (U6) verifies *claims*, not paragraphs, so the first stage of the
pipeline splits a draft into the smallest independently-checkable assertions.
This splitter is deterministic and rule-based (no model): it breaks the draft on
sentence terminators, then further splits each sentence on coordinating
conjunctions and semicolons so that "It has 3 beds and a renovated kitchen"
becomes two claims that can be cited (or blocked) independently.

Keeping this rule-based makes the safety pipeline hermetic and reproducible — the
same draft always yields the same claims — and matches the RAG layer's
no-network, deterministic-fake philosophy. A later unit may swap in an
LLM-backed claim extractor behind the same ``decompose`` signature.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

# Sentence terminators (., !, ?) — split but keep meaningful clause boundaries.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Intra-sentence clause separators: coordinating conjunctions and semicolons.
# Splitting on these turns conjoined assertions into separate atomic claims.
_CLAUSE_SPLIT = re.compile(r"\s*;\s*|\s+\band\b\s+|\s+\bbut\b\s+|\s+\bwhile\b\s+")


@dataclass(frozen=True)
class Claim:
    """One atomic, independently-verifiable assertion drawn from a draft.

    ``text`` is the claim's surface form (used to retrieve evidence and entail).
    ``index`` is its position in the original draft, preserved so the Critic's
    per-claim verdicts can be re-associated with the message for logging.
    """

    text: str
    index: int


def _clean(fragment: str) -> str:
    """Trim whitespace and dangling separators from a clause fragment."""
    return fragment.strip().strip(",;").strip()


def split_claims(draft: str) -> List[str]:
    """Split ``draft`` into atomic claim strings (deterministic, rule-based).

    Empty / whitespace-only drafts yield ``[]``. Sentences are split on
    terminators, then each sentence on conjunctions/semicolons; blank fragments
    are dropped. Trailing punctuation is preserved on sentence-final claims.
    """
    if not draft or not draft.strip():
        return []
    claims: List[str] = []
    for sentence in _SENTENCE_SPLIT.split(draft.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        for clause in _CLAUSE_SPLIT.split(sentence):
            cleaned = _clean(clause)
            if cleaned:
                claims.append(cleaned)
    return claims


def decompose(draft: str) -> List[Claim]:
    """Decompose ``draft`` into indexed :class:`Claim`s for the Critic.

    Thin wrapper over :func:`split_claims` that attaches the original ordering,
    so each per-claim verdict downstream stays traceable to its place in the
    message.
    """
    return [Claim(text=text, index=i) for i, text in enumerate(split_claims(draft))]
