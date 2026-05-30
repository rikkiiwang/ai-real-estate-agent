"""Promulgated TREC-form filling (U12) — blanks ONLY, never clause language.

Texas law lets a non-attorney *fill the blanks* of a promulgated TREC form
(parties, property, price, dates, earnest money, and a SELECTION among the
form's own enumerated options) but makes authoring or modifying clause language
the unauthorized practice of law (UPL). This module encodes exactly that line as
structured data + a pure :func:`fill_trec_form` function:

* The template (:data:`TREC_1_4_FAMILY_RESALE`) is the promulgated form modelled
  as structured fields — a fixed set of factual blanks plus a fixed ENUMERATED
  set of standard contingencies the form itself offers. Nothing here is free
  text the AI authors.
* :func:`fill_trec_form` populates the factual blanks and SELECTS contingencies
  from that enumerated set. It NEVER emits clause prose.
* Any request for a custom clause, a non-standard term, or an unrecognised
  contingency raises :class:`UplViolation` — the typed escalation signal. The
  Closer (U10/U12) catches it and routes to ``lawyer.handoff.decide`` rather than
  ever generating clause text.

This module is deterministic, stdlib-only, and does not touch the network, the
Rails domain, or any model. It is the data + boundary; the Closer is the policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional


# --------------------------------------------------------------------------- #
# The enumerated, promulgated contingency set. These are SELECTIONS the form
# itself offers — the AI may tick them, it may NOT reword them or add new ones.
# --------------------------------------------------------------------------- #
class Contingency(str, Enum):
    """Standard contingencies the promulgated 1-4 family resale form enumerates.

    A SELECTION among these is a ministerial blank-fill. Anything outside this
    set is a non-standard term and a UPL boundary (see :func:`fill_trec_form`).
    """

    FINANCING = "financing_contingency"          # third-party financing addendum
    INSPECTION = "inspection_option_period"       # buyer's option / inspection
    APPRAISAL = "appraisal_contingency"
    TITLE_REVIEW = "title_review"
    SURVEY = "survey"
    HOA_REVIEW = "hoa_addendum"


# A cash acquisition offer waives financing by definition; this is the set a cash
# offer may legitimately select from (still all promulgated selections).
CASH_OFFER_CONTINGENCIES: tuple[Contingency, ...] = (
    Contingency.INSPECTION,
    Contingency.APPRAISAL,
    Contingency.TITLE_REVIEW,
    Contingency.SURVEY,
    Contingency.HOA_REVIEW,
)


# --------------------------------------------------------------------------- #
# Typed escalation signal for the UPL boundary.
# --------------------------------------------------------------------------- #
class UplViolation(Exception):
    """Raised when a request crosses the UPL line (custom/non-standard clause).

    Carries the offending ``request`` text/term and a ``reason`` so the Closer
    can fold it straight into a handoff packet. The presence of this exception is
    the contract: a custom-clause request NEVER returns a filled form, and no
    clause text is ever generated.
    """

    def __init__(self, request: str, reason: str) -> None:
        self.request = request
        self.reason = reason
        super().__init__(f"UPL boundary: {reason} (request: {request!r})")


# --------------------------------------------------------------------------- #
# The promulgated form, modelled as structured data (blanks + enumerated set).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TrecFormTemplate:
    """A promulgated TREC form as structured data — blanks + enumerated options.

    ``form_id`` / ``title`` identify the promulgated form. ``factual_blanks`` is
    the fixed set of factual fields a non-attorney may fill. ``contingencies`` is
    the fixed ENUMERATED set the form offers for selection. NOTHING here is
    authored prose; the AI only chooses among these and fills the factual blanks.
    """

    form_id: str
    title: str
    factual_blanks: tuple[str, ...]
    contingencies: tuple[Contingency, ...]


# The MVP target: TREC 20-x One to Four Family Residential Contract (Resale).
TREC_1_4_FAMILY_RESALE = TrecFormTemplate(
    form_id="TREC-20",
    title="One to Four Family Residential Contract (Resale)",
    factual_blanks=(
        "seller_name",
        "buyer_name",
        "property_address",
        "sales_price",
        "earnest_money",
        "effective_date",
        "closing_date",
    ),
    contingencies=CASH_OFFER_CONTINGENCIES,
)


@dataclass(frozen=True)
class TrecTerms:
    """The structured deal terms a form-fill consumes — factual blanks only.

    Every field is a FACT (a party, the property, a number, a date) or a
    SELECTION from the enumerated contingency set. ``custom_clause_request``
    exists ONLY so a caller can pass through a consumer's non-standard ask and
    have :func:`fill_trec_form` detect it and refuse — it is never written into a
    form.
    """

    seller_name: str
    buyer_name: str
    property_address: str
    sales_price: float
    earnest_money: float
    effective_date: str
    closing_date: str
    selected_contingencies: tuple[Contingency, ...] = ()
    # Pass-through for a consumer's non-standard request, if any. Detected and
    # refused (UPL); NEVER authored into the form.
    custom_clause_request: Optional[str] = None


@dataclass(frozen=True)
class FilledForm:
    """A promulgated form with its factual blanks filled and options selected.

    ``form_id`` / ``title`` echo the promulgated template. ``blanks`` maps each
    factual blank to its filled value (strings/numbers only — no prose).
    ``selected_contingencies`` are the ticked enumerated options. There is NO
    field for free-text clauses by construction: this dataclass cannot carry
    authored clause language, so the UPL boundary is structural, not just a check.
    """

    form_id: str
    title: str
    blanks: Mapping[str, object]
    selected_contingencies: tuple[Contingency, ...] = ()

    def to_dict(self) -> dict:
        """Plain-dict view for the audit store / the Rails offer payload."""
        return {
            "form_id": self.form_id,
            "title": self.title,
            "blanks": dict(self.blanks),
            "selected_contingencies": [c.value for c in self.selected_contingencies],
        }


# --------------------------------------------------------------------------- #
# Fill.
# --------------------------------------------------------------------------- #
def _validate_factual_blanks(terms: TrecTerms) -> dict[str, object]:
    """Collect + sanity-check the factual blanks; raise ValueError on bad facts.

    These are ministerial validations (a price must be positive, a name/address
    must be present) — NOT clause authoring.
    """
    if not terms.seller_name or not terms.seller_name.strip():
        raise ValueError("seller_name is a required factual blank")
    if not terms.buyer_name or not terms.buyer_name.strip():
        raise ValueError("buyer_name is a required factual blank")
    if not terms.property_address or not terms.property_address.strip():
        raise ValueError("property_address is a required factual blank")
    if terms.sales_price <= 0:
        raise ValueError("sales_price must be a positive number")
    if terms.earnest_money < 0:
        raise ValueError("earnest_money cannot be negative")
    if not terms.effective_date or not terms.effective_date.strip():
        raise ValueError("effective_date is a required factual blank")
    if not terms.closing_date or not terms.closing_date.strip():
        raise ValueError("closing_date is a required factual blank")
    return {
        "seller_name": terms.seller_name.strip(),
        "buyer_name": terms.buyer_name.strip(),
        "property_address": terms.property_address.strip(),
        "sales_price": round(float(terms.sales_price), 2),
        "earnest_money": round(float(terms.earnest_money), 2),
        "effective_date": terms.effective_date.strip(),
        "closing_date": terms.closing_date.strip(),
    }


def _validate_contingencies(
    selected: tuple[Contingency, ...],
    template: TrecFormTemplate,
) -> tuple[Contingency, ...]:
    """Ensure every selection is a member of the form's enumerated option set.

    A selection outside the promulgated set is a non-standard term — the UPL
    boundary — and raises :class:`UplViolation`, never a silent drop.
    """
    allowed = set(template.contingencies)
    out: list[Contingency] = []
    for c in selected:
        if not isinstance(c, Contingency) or c not in allowed:
            raise UplViolation(
                request=str(c),
                reason=(
                    "selected contingency is not one of the form's enumerated "
                    "promulgated options; a non-standard term cannot be authored"
                ),
            )
        if c not in out:  # de-dupe, preserve order
            out.append(c)
    return tuple(out)


def fill_trec_form(
    terms: TrecTerms,
    template: TrecFormTemplate = TREC_1_4_FAMILY_RESALE,
) -> FilledForm:
    """Fill a promulgated TREC form's blanks from ``terms`` — blanks ONLY.

    Populates the factual blanks (parties, property, price, earnest money,
    dates) and selects contingencies from the template's ENUMERATED set. It does
    NOT author or modify any clause language.

    Raises
    ------
    UplViolation
        If ``terms`` carries a custom/non-standard clause request, or selects a
        contingency outside the form's enumerated promulgated set. This is the
        typed escalation signal — the caller routes it to a human; NO clause text
        is generated.
    ValueError
        If a required factual blank is missing or invalid (a ministerial check).
    """
    # UPL boundary FIRST: a custom-clause request never yields a form.
    if terms.custom_clause_request and terms.custom_clause_request.strip():
        raise UplViolation(
            request=terms.custom_clause_request.strip(),
            reason=(
                "request to author/modify a custom contract clause or non-standard "
                "term — non-attorney may only fill promulgated-form blanks (UPL)"
            ),
        )

    blanks = _validate_factual_blanks(terms)
    selected = _validate_contingencies(terms.selected_contingencies, template)
    return FilledForm(
        form_id=template.form_id,
        title=template.title,
        blanks=blanks,
        selected_contingencies=selected,
    )


__all__ = [
    "Contingency",
    "CASH_OFFER_CONTINGENCIES",
    "UplViolation",
    "TrecFormTemplate",
    "TREC_1_4_FAMILY_RESALE",
    "TrecTerms",
    "FilledForm",
    "fill_trec_form",
]
