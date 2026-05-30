"""The grounded generator node (U10).

This is the piece U6 always assumed but never owned: a generator the Critic can
verify. The Critic is a FIXED verify-only pipeline — it never writes a draft —
so without a generator there is nothing to gate. This module closes that gap.

The contract that makes the loop honest: the generator does NOT invent prose. It

1. runs the U3 AVM (``estimate_value``) for the address,
2. INGESTS the resulting facts into the RAG store (via the U5 ``valuation_facts``
   ingest adapter) — including a ``valuation_run`` fact stating the estimate — so
   the Critic can later retrieve and entail them, and
3. composes the customer-facing draft FROM those same fact ``content`` strings.

Because every sentence in the draft is built from a fact that now lives in the
store, the Critic's retrieve -> entail step finds a supporting source for each
claim and binds a citation: the draft is grounded BY CONSTRUCTION. An
insufficient-data valuation (no ingested coverage) yields a no-claim draft so
the Critic has nothing to (wrongly) approve.

The generator imports the valuation package's public ``estimate_value`` and the
RAG ``valuation_facts`` adapter only — it never reaches into their internals,
and it never imports the Critic (the verifier stays separate from the writer).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from brain.lawyer.fair_housing import scan_output
from brain.rag import Retriever, valuation_facts
from brain.valuation import estimate_value


@dataclass(frozen=True)
class GeneratedDraft:
    """A grounded draft plus whether it had ingested coverage.

    ``draft`` is the customer-facing message, every sentence of which was built
    from a fact ingested into the RAG store this run. ``sufficient_data`` is
    ``False`` when the address had no coverage (the draft makes no claims).
    ``run_id`` is the stable id the valuation facts were ingested under (so the
    audit trail can tie the draft back to its source facts).
    """

    draft: str
    sufficient_data: bool
    run_id: str


def _run_id(address: str) -> str:
    """A stable per-address valuation run id (deterministic for tests/upsert)."""
    slug = "".join(ch if ch.isalnum() else "-" for ch in address.lower()).strip("-")
    return f"valrun:{slug or 'unknown'}"


def generate_grounded_draft(
    address: str,
    retriever: Retriever,
    *,
    condition: Optional[float] = None,
    revise_from: Optional[str] = None,
) -> GeneratedDraft:
    """Value ``address``, ingest the facts, and compose a grounded draft.

    Steps:

    * Call the AVM (``estimate_value``). An insufficient-data result returns a
      no-claim draft and ingests nothing (nothing grounded to retrieve).
    * Otherwise convert the valuation into provenance-tagged facts with
      ``valuation_facts`` and ingest them into the injected ``retriever``'s store
      (a ``valuation_run`` estimate fact + one fact per feature contribution).
    * Build the draft sentences from those facts' ``content`` so each claim has a
      matching source in the store. ``revise_from`` lets the bounded-regenerate
      step seed the draft from the Critic's stripped ``approved_message`` instead
      of the full template; it is still re-verified afterwards.

    The returned draft is grounded BY CONSTRUCTION: every sentence traces to a
    fact now present in the store.
    """
    valuation = estimate_value(address, condition=condition)
    run_id = _run_id(address)

    if not getattr(valuation, "sufficient_data", False):
        # Honesty over precision: no coverage -> a no-claim draft. The Critic
        # treats an empty draft as approved-but-empty; the orchestrator routes a
        # no-claim outcome to a human rather than sending a fabricated number.
        return GeneratedDraft(
            draft=(
                f"We don't yet have enough source data on {address} to share a "
                f"valuation."
            ),
            sufficient_data=False,
            run_id=run_id,
        )

    facts = valuation_facts(address, valuation, run_id=run_id)
    retriever.ingest_many(facts)

    # If the regenerate step handed us a stripped, already-supported message,
    # reuse it verbatim as the draft body — it is built only from supported
    # claims, so it re-verifies cleanly while dropping the unsupported sentence.
    if revise_from is not None and revise_from.strip():
        return GeneratedDraft(
            draft=revise_from.strip(),
            sufficient_data=True,
            run_id=run_id,
        )

    # Compose the draft straight from the ingested facts' content. Using the
    # fact text verbatim is what guarantees the Critic retrieves a supporting
    # source and entails each claim (grounded by construction).
    #
    # We pre-screen each candidate sentence through the SAME Fair Housing
    # wording rail (U7) the orchestrator will gate on, dropping any sentence
    # whose wording would trip it — e.g. the raw "Property age (years)" feature
    # label collides with the deny-list term "age". Every fact is still ingested
    # above (the store stays complete for the Critic), but the customer-facing
    # draft only surfaces FH-clean, grounded sentences. The headline estimate
    # fact is always FH-clean, so the draft always carries at least one cited,
    # supported claim on the happy path.
    sentences = [
        fact.content for fact in facts if scan_output(fact.content).allowed
    ]
    draft = " ".join(sentences)
    return GeneratedDraft(draft=draft, sufficient_data=True, run_id=run_id)
