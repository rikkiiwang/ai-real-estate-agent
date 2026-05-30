"""Fair Housing output rail — a separate, non-negotiable gate over *wording*.

This rail is deliberately decoupled from factual verification (the Critic, U6):
a claim can be perfectly true and still be an illegal steering act. The
disparate-impact gate (``valuation.fairness_audit``) catches bias that lives in
the *numbers*; this rail catches bias that lives in the *words* of consumer-
facing output — protected-class references and the coded proxies ("safe",
"good schools", "family-friendly") that courts and HUD treat as steering.

It runs as an OUTPUT gate before send. A trip does not silently drop text: it
returns a structured :class:`FairHousingResult` with ``allowed=False`` and
``escalate=True`` carrying a logged reason, so the orchestrator (U13) routes to
human handoff (U8) and the audit store (U9) records why. The term/proxy lists
are *data* (module-level tuples) so they are easy to extend without touching the
scanning logic.

Scope of the deny-list:

* the 7 FEDERAL protected classes (Fair Housing Act): race, color, national
  origin, religion, sex (incl. sexual orientation & gender identity per
  *Bostock*-aligned HUD guidance), familial status, disability;
* the City of AUSTIN ordinance additions: sexual orientation, gender identity,
  age, marital status, student status, source of income;
* known PROXIES / coded steering language: desirability descriptors ("safe",
  "good/great schools", "family-friendly", "nice area"), crime-stats-as-
  desirability, and demographic descriptors.

``equal_service`` is a documenting marker, not a branch: qualification and
listing-set logic elsewhere MUST NOT branch on inferred protected attributes.
No behavioral branching happens here — this module is only the wording rail.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional

# --------------------------------------------------------------------------- #
# Protected-class terms — DATA. Each entry is a category label mapped to the
# surface terms that, appearing in consumer-facing output, reference (or invite
# inference of) a protected class. Extend by editing these tuples; the scanner
# is generic over them. Matching is word-boundary, case-insensitive.
# --------------------------------------------------------------------------- #

# The 7 federal protected classes (Fair Housing Act, 42 U.S.C. § 3604).
FEDERAL_PROTECTED_CLASSES: dict[str, tuple[str, ...]] = {
    "race": (
        "race", "racial", "black", "white", "asian", "hispanic", "latino",
        "latina", "latinx", "caucasian", "african american", "african-american",
        "minority", "minorities", "people of color",
    ),
    "color": ("color", "colored", "skin color"),
    "national_origin": (
        "national origin", "ethnicity", "ethnic", "foreign", "immigrant",
        "immigrants", "mexican", "indian", "chinese", "nationality",
    ),
    "religion": (
        "religion", "religious", "christian", "catholic", "muslim", "islamic",
        "jewish", "hindu", "buddhist", "church", "mosque", "synagogue", "temple",
    ),
    "sex": (
        "sex", "gender", "male", "female", "man", "woman", "men", "women",
        # Sex includes sexual orientation & gender identity (HUD guidance).
        "gay", "lesbian", "lgbt", "lgbtq", "homosexual", "heterosexual",
        "transgender", "trans", "cisgender", "queer",
    ),
    "familial_status": (
        "familial status", "family status", "children", "childless", "kids",
        "no kids", "adults only", "adult community", "couples", "singles only",
        "empty nester", "empty nesters", "newlywed", "newlyweds",
    ),
    "disability": (
        "disability", "disabled", "handicap", "handicapped", "wheelchair",
        "able-bodied", "mental illness", "mentally ill", "blind", "deaf",
    ),
}

# City of Austin ordinance additions (Austin City Code Ch. 5-4). Some overlap
# the federal "sex" reading; kept distinct so audit reasons name the ordinance.
AUSTIN_ORDINANCE_CLASSES: dict[str, tuple[str, ...]] = {
    "sexual_orientation": ("sexual orientation", "orientation", "straight"),
    "gender_identity": ("gender identity", "gender expression", "nonbinary",
                        "non-binary"),
    "age": (
        "age", "elderly", "senior", "seniors", "young", "youthful", "retiree",
        "retirees", "millennial", "millennials", "boomer", "boomers",
    ),
    "marital_status": (
        "marital status", "married", "unmarried", "single people", "divorced",
        "widowed", "bachelor",
    ),
    "student_status": ("student", "students", "non-student", "college kids"),
    "source_of_income": (
        "source of income", "section 8", "housing voucher", "vouchers",
        "welfare", "public assistance", "no voucher", "no section 8",
    ),
}

# --------------------------------------------------------------------------- #
# Proxies / coded steering language — DATA. These are not protected-class words
# on their own, but HUD treats them as steering when applied to a neighborhood:
# they signal *who belongs* without naming a class. Tripping a proxy blocks and
# escalates exactly like a protected-class term.
# --------------------------------------------------------------------------- #
STEERING_PROXIES: dict[str, tuple[str, ...]] = {
    "desirability_steering": (
        "safe neighborhood", "safe area", "safe part of town", "unsafe area",
        "unsafe neighborhood", "bad neighborhood", "bad area", "rough area",
        "rough neighborhood", "sketchy", "good area", "great area", "nice area",
        "nicer area", "desirable area", "desirable neighborhood", "good part of town",
        "up-and-coming", "up and coming", "transitional neighborhood",
    ),
    "school_steering": (
        "good schools", "great schools", "great school district", "best schools",
        "bad schools", "poor schools", "low-rated schools", "top schools",
        "good school district", "right schools",
    ),
    "family_steering": (
        "family-friendly", "family friendly", "great for families",
        "good for families", "perfect for families", "family neighborhood",
        "family-oriented", "kid-friendly", "kid friendly",
    ),
    "crime_steering": (
        "crime rate", "crime rates", "high crime", "low crime", "crime-free",
        "crime free", "crime statistics", "criminal element", "gang", "gangs",
    ),
    "demographic_descriptor": (
        "people like you", "people like me", "your kind", "our kind",
        "your community", "the right people", "the right kind of people",
        "fits in", "belong here", "type of people", "those people", "this element",
    ),
}


@dataclass(frozen=True)
class Term:
    """A single matchable deny-list term and its provenance (loggable)."""

    phrase: str
    category: str
    # One of: "federal", "austin", "proxy".
    source: str


def _build_terms() -> tuple[Term, ...]:
    """Flatten the DATA tables into a single ordered term list (longest-first).

    Longest-first ordering means multi-word proxies ("safe neighborhood") are
    reported in preference to a bare class word they may contain, giving the
    most specific audit reason.
    """
    terms: list[Term] = []
    for category, phrases in FEDERAL_PROTECTED_CLASSES.items():
        terms.extend(Term(p, category, "federal") for p in phrases)
    for category, phrases in AUSTIN_ORDINANCE_CLASSES.items():
        terms.extend(Term(p, category, "austin") for p in phrases)
    for category, phrases in STEERING_PROXIES.items():
        terms.extend(Term(p, category, "proxy") for p in phrases)
    terms.sort(key=lambda t: len(t.phrase), reverse=True)
    return tuple(terms)


# Compiled once at import: the full ordered deny-list and a single regex that
# alternates over every phrase with word boundaries, scanned case-insensitively.
DENY_LIST: tuple[Term, ...] = _build_terms()
_PHRASE_TO_TERM: dict[str, Term] = {t.phrase: t for t in DENY_LIST}
_DENY_RE = re.compile(
    r"\b(" + "|".join(re.escape(t.phrase) for t in DENY_LIST) + r")\b",
    re.IGNORECASE,
)


@dataclass
class FairHousingMatch:
    """One deny-list hit in scanned output (loggable)."""

    matched_text: str
    phrase: str
    category: str
    source: str


@dataclass
class FairHousingResult:
    """Structured result of the Fair Housing rail, for the audit store later.

    ``allowed`` is the send decision: ``True`` means the wording rail found no
    protected-class term/proxy and no opinion answer to a subjective question.
    ``escalate=True`` means a trip occurred and the orchestrator must route to
    human handoff (U8) — output is NEVER silently dropped. ``reason`` is the
    human-readable audit line. ``redirected_response`` carries a neutral
    third-party redirect when the trip was a subjective question (see
    ``redirect_policy``); otherwise ``None``. ``matches`` records the offending
    terms for the audit log.
    """

    allowed: bool
    escalate: bool
    reason: str
    redirected_response: Optional[str] = None
    matches: list[FairHousingMatch] = field(default_factory=list)

    def to_dict(self) -> dict:
        """A plain-dict view for logging to the audit store later."""
        return asdict(self)


def find_protected_terms(text: str) -> list[FairHousingMatch]:
    """Return every deny-list term/proxy found in ``text`` (deterministic).

    Word-boundary, case-insensitive scan over the DATA-driven deny-list. The
    list is data; extend the module tables, not this function.
    """
    matches: list[FairHousingMatch] = []
    for m in _DENY_RE.finditer(text or ""):
        term = _PHRASE_TO_TERM[m.group(0).lower()]
        matches.append(
            FairHousingMatch(
                matched_text=m.group(0),
                phrase=term.phrase,
                category=term.category,
                source=term.source,
            )
        )
    return matches


def scan_output(text: str) -> FairHousingResult:
    """Scan consumer-facing output for protected-class terms/proxies.

    This is the wording half of the rail: if any deny-list term or steering
    proxy appears, the output is BLOCKED (``allowed=False``) and escalates with
    a logged reason naming the categories and offending phrases. Clean text
    passes. The subjective-question half lives in ``redirect_policy``; the
    composed gate is :func:`review_output`.
    """
    matches = find_protected_terms(text)
    if not matches:
        return FairHousingResult(
            allowed=True,
            escalate=False,
            reason="fair_housing: no protected-class term or steering proxy found",
            matches=[],
        )

    categories = sorted({f"{m.source}:{m.category}" for m in matches})
    phrases = sorted({m.matched_text for m in matches})
    reason = (
        "fair_housing: BLOCKED — protected-class term/proxy in output; "
        f"categories={categories}; phrases={phrases}"
    )
    return FairHousingResult(
        allowed=False,
        escalate=True,
        reason=reason,
        matches=matches,
    )


# --------------------------------------------------------------------------- #
# Equal-service marker. Documenting guarantee, NOT a branch.
# --------------------------------------------------------------------------- #
EQUAL_SERVICE_GUARANTEE: str = (
    "Equal service: qualification flow and listing sets MUST be identical "
    "regardless of any inferred protected attribute. Qualification logic must "
    "not branch on inferred race, color, national origin, religion, sex, "
    "sexual orientation, gender identity, familial status, disability, age, "
    "marital status, student status, or source of income."
)


def equal_service() -> str:
    """Return the equal-service guarantee statement (a marker, not a branch).

    Present so callers can assert the guarantee is documented and surface it in
    audits. It performs no per-user logic: there is intentionally NO behavioral
    branching on inferred attributes anywhere in this rail.
    """
    return EQUAL_SERVICE_GUARANTEE
