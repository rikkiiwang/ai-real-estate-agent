"""Property matching — the buyer-side Brain seam for U14.

Given a structured :class:`~brain.orchestrator.buyer_intake.BuyerRequest` (its
neutral ``criteria``) and an INJECTED list of candidate listings, this module
filters the candidates on NEUTRAL criteria only and, for each surviving match,
surfaces the property's valuation + photo-finding intelligence as CITED claims.

Two hard contracts (both unit-pinned):

1. **Equal service / Fair Housing (R12, U7).** Matching filters ONLY on the
   neutral search criteria the buyer gave (beds / baths / price ceiling / sqft /
   location / property type). It NEVER branches on an inferred protected
   attribute or a known proxy. A candidate carries arbitrary fields; the matcher
   reads a fixed neutral allow-list off each candidate and nothing else, so the
   match set is identical whether or not an inferred-attribute field is present.

2. **No fabrication (R1 honesty).** Over-constrained criteria return an EMPTY
   match list — the matcher never invents a property to satisfy a buyer. A match
   only surfaces claims that are GROUNDED in the candidate's valuation/photo
   data; a candidate with no such intelligence yields a match with no claims,
   never a made-up one.

The cited-intelligence seam (R3, R11)
-------------------------------------
For each match we build provenance-tagged FACTS from the candidate's valuation
run and photo findings using the existing RAG ingest adapters
(:func:`brain.rag.valuation_facts`, :func:`brain.rag.photo_finding_facts`) — the
same shapes the Critic (U6) cites. The matcher then turns each fact into a
:class:`MatchClaim` (claim text + its backing ``source_id``/``kind``), which is
a claim object *ready for verification*.

How the Critic/FH verification path is wired here:

* If a :class:`~brain.lawyer.critic.Critic` is injected, the match's facts are
  ingested into the Critic's retriever and each claim is run through
  ``Critic.verify`` (decompose -> retrieve -> entail -> cite -> gate); only
  claims the Critic APPROVES (entailed + cited) are surfaced as ``verified``,
  and the draft is additionally screened by the U7 Fair-Housing wording rail
  (:func:`brain.lawyer.fair_housing.scan_output`). This is the full build-
  orchestrator verification path applied to match intelligence.
* If NO critic is injected, the claims are returned UNVERIFIED with their
  backing source ids attached — i.e. claim objects *ready for verification* by
  the orchestrator's verify pass. This is the documented seam: callers wiring the
  full graph pass a critic; callers surfacing claims for a later verify pass do
  not. Either way no claim is surfaced without a citation.

This module imports the Brain's existing units (RAG adapters, Critic, FH rail)
and never reaches the network; the candidate listings, valuation, photo
findings, and critic are all injected.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from brain.lawyer.critic import Critic
from brain.lawyer.fair_housing import FairHousingResult, scan_output
from brain.rag import Fact, photo_finding_facts, valuation_facts

from .buyer_intake import BuyerRequest, NEUTRAL_CRITERIA_FIELDS

# The neutral candidate fields the matcher reads to filter. Mirrors the buyer's
# neutral search criteria. NOTHING outside this set is ever read for a match
# decision — that is the equal-service structural guarantee. Extend only with
# neutral, transaction-relevant fields; never a protected-class proxy.
CANDIDATE_NEUTRAL_FIELDS: tuple[str, ...] = (
    "beds",
    "baths",
    "price",
    "sqft",
    "location",
    "property_type",
)


@dataclass(frozen=True)
class MatchClaim:
    """One piece of cited intelligence about a matched property.

    ``text`` is the human-readable claim; ``source_id``/``kind`` bind it to the
    grounded source it came from (a valuation run or a photo finding), so it is a
    claim object READY FOR VERIFICATION (and, post-verify, a cited claim).
    ``verified`` is set once a Critic has approved + cited it.
    """

    text: str
    source_id: str
    kind: str
    verified: bool = False

    @classmethod
    def from_fact(cls, fact: Fact) -> "MatchClaim":
        """Build an (unverified) claim from a provenance-tagged RAG fact."""
        return cls(text=fact.content, source_id=fact.source_id, kind=fact.kind)


@dataclass(frozen=True)
class PropertyMatch:
    """A candidate that satisfied the buyer's neutral criteria, with intelligence.

    ``listing_id``/``address`` identify the property. ``criteria_met`` is the
    fixed neutral allow-list of fields that were compared (audit trail of WHAT
    was matched on — proving no proxy was used). ``claims`` is the cited
    intelligence (valuation + photo findings) surfaced for this match.
    ``fair_housing`` is the U7 wording-rail result over the surfaced claim text
    (``None`` when no critic/FH pass ran).
    """

    listing_id: str
    address: str
    criteria_met: tuple[str, ...]
    claims: List[MatchClaim] = field(default_factory=list)
    fair_housing: Optional[FairHousingResult] = None

    @property
    def verified_claims(self) -> List[MatchClaim]:
        """Only the claims a Critic approved + cited (empty when unverified)."""
        return [c for c in self.claims if c.verified]


def _candidate_get(candidate: Any, key: str) -> Any:
    """Read ``key`` off a candidate that may be a mapping or an object.

    Reads ONLY the requested (neutral) key — never iterates the candidate's
    fields — so an inferred-attribute field on the candidate is structurally
    unreachable by the matcher.
    """
    if isinstance(candidate, Mapping):
        return candidate.get(key)
    return getattr(candidate, key, None)


def _matches_criteria(
    candidate: Any,
    criteria: Mapping[str, Any],
) -> Optional[tuple[str, ...]]:
    """Return the neutral fields compared if the candidate meets the criteria.

    Returns ``None`` when the candidate fails ANY criterion (drops it from the
    result — never fabricated). The comparison reads only the fixed neutral
    allow-list; an absent candidate value fails the corresponding criterion
    rather than guessing.
    """
    compared: list[str] = []

    def fail(field_name: str) -> None:
        compared.append(field_name)

    # min_beds / min_baths / min_sqft — candidate must meet-or-exceed.
    for crit_key, cand_key in (
        ("min_beds", "beds"),
        ("min_baths", "baths"),
        ("min_sqft", "sqft"),
    ):
        want = criteria.get(crit_key)
        if want is None:
            continue
        have = _candidate_get(candidate, cand_key)
        compared.append(cand_key)
        if have is None or float(have) < float(want):
            return None

    # max_price — candidate price must be at-or-below the ceiling.
    ceiling = criteria.get("max_price")
    if ceiling is not None:
        price = _candidate_get(candidate, "price")
        compared.append("price")
        if price is None or float(price) > float(ceiling):
            return None

    # location / property_type — case-insensitive exact-token match.
    for crit_key, cand_key in (
        ("location", "location"),
        ("property_type", "property_type"),
    ):
        want = criteria.get(crit_key)
        if want is None:
            continue
        have = _candidate_get(candidate, cand_key)
        compared.append(cand_key)
        if have is None or str(have).strip().lower() != str(want).strip().lower():
            return None

    return tuple(compared)


def _candidate_facts(candidate: Any, address: str) -> List[Fact]:
    """Build provenance-tagged facts from a candidate's valuation + photos.

    Uses the existing RAG ingest adapters so the produced facts are the exact
    cite-able shapes the Critic consumes. A candidate may carry:

    * ``valuation`` — a duck-typed U3 ``Valuation`` (``sufficient_data``, ...).
    * ``photo_findings`` — an iterable of duck-typed U4 ``Finding`` objects.
    * ``listing_id`` — used to scope the valuation run id.

    A candidate with neither yields NO facts (so the match surfaces no claims —
    never a fabricated one).
    """
    facts: List[Fact] = []
    valuation = _candidate_get(candidate, "valuation")
    if valuation is not None:
        listing_id = _candidate_get(candidate, "listing_id") or address
        facts.extend(valuation_facts(address, valuation, run_id=f"match:{listing_id}"))
    findings = _candidate_get(candidate, "photo_findings")
    if findings:
        facts.extend(photo_finding_facts(address, findings))
    return facts


def _verify_claims(
    facts: Sequence[Fact],
    critic: Critic,
) -> tuple[List[MatchClaim], FairHousingResult]:
    """Run the candidate's facts through the Critic + Fair-Housing path.

    Ingests the facts into the Critic's retriever, verifies a draft composed of
    the claim texts, and returns (claims, fair_housing). A claim is marked
    ``verified`` iff the Critic approved + cited it. The composed claim text is
    also screened by the U7 wording rail so steering language never surfaces.
    """
    critic.retriever.ingest_many(facts)
    draft = " ".join(f.content for f in facts)
    fair_housing = scan_output(draft)

    result = critic.verify(draft)
    # Map each supported (entailed + cited) verdict's citation back to its fact.
    cited_sources = {
        v.citation for v in result.claims if v.supported and v.citation is not None
    }
    claims: List[MatchClaim] = []
    for fact in facts:
        claims.append(
            MatchClaim(
                text=fact.content,
                source_id=fact.source_id,
                kind=fact.kind,
                # A claim is verified only if the Critic approved the draft (no
                # contradiction / FH trip) AND this fact's source was cited.
                verified=(
                    result.approved
                    and fair_housing.allowed
                    and fact.source_id in cited_sources
                ),
            )
        )
    return claims, fair_housing


def match_properties(
    buyer_request: BuyerRequest,
    candidates: Iterable[Any],
    *,
    critic: Optional[Critic] = None,
) -> List[PropertyMatch]:
    """Match a buyer's neutral criteria against injected candidate listings.

    Parameters
    ----------
    buyer_request:
        The structured :class:`~brain.orchestrator.buyer_intake.BuyerRequest`;
        only its neutral ``criteria`` are used to filter.
    candidates:
        An injected iterable of candidate listings. Each may be a mapping or an
        object carrying the neutral fields in :data:`CANDIDATE_NEUTRAL_FIELDS`
        plus, optionally, ``listing_id``, ``address``, ``valuation`` (a U3
        ``Valuation``), and ``photo_findings`` (U4 findings) for cited
        intelligence. Any non-neutral field on a candidate is never read.
    critic:
        Optional injected :class:`~brain.lawyer.critic.Critic`. When provided,
        each match's intelligence is verified through the Critic + Fair-Housing
        path and only approved-and-cited claims are marked ``verified``. When
        omitted, claims are returned UNVERIFIED but already bound to their source
        ids (ready for the orchestrator's verify pass) — the documented seam.

    Returns
    -------
    list[PropertyMatch]
        Matches in candidate order. EMPTY when the criteria are over-constrained
        — never a fabricated match.

    Notes
    -----
    Equal service: the filter reads ONLY :data:`CANDIDATE_NEUTRAL_FIELDS` off
    each candidate, so the match set is identical regardless of any inferred
    protected attribute present on the candidate or the request.
    """
    criteria = dict(buyer_request.criteria)
    matches: List[PropertyMatch] = []

    for candidate in candidates:
        compared = _matches_criteria(candidate, criteria)
        if compared is None:
            continue  # over-constrained for this candidate: drop, never fabricate

        listing_id = str(_candidate_get(candidate, "listing_id") or "")
        address = str(
            _candidate_get(candidate, "address") or listing_id or "unknown"
        )
        facts = _candidate_facts(candidate, address)

        if critic is not None and facts:
            claims, fair_housing = _verify_claims(facts, critic)
        else:
            claims = [MatchClaim.from_fact(f) for f in facts]
            fair_housing = None

        matches.append(
            PropertyMatch(
                listing_id=listing_id,
                address=address,
                criteria_met=compared,
                claims=claims,
                fair_housing=fair_housing,
            )
        )

    return matches


__all__ = [
    "MatchClaim",
    "PropertyMatch",
    "match_properties",
    "CANDIDATE_NEUTRAL_FIELDS",
]
