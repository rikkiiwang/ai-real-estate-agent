"""Subjective-question redirect policy + the composed Fair Housing output gate.

The wording deny-list (``fair_housing.scan_output``) catches protected-class
terms and proxies in *output*. This module covers the other steering vector:
SUBJECTIVE neighborhood questions ("is it safe?", "good schools?", "is this a
[demographic] area?"). HUD guidance is that an agent must not answer these with
an *opinion* — doing so is steering even when no class is named. The neutral
response is to REDIRECT the consumer to objective third-party sources (HUD, the
TEA school ratings portal, public crime data) so they evaluate for themselves.

Neutral FACTUAL answers — price, beds/baths, sqft, commute distance, tax rate —
are not subjective and pass unchanged.

:func:`review_output` is the single OUTPUT gate the orchestrator (U13) calls
before send. It composes both halves:

1. scan the drafted answer's wording (deny-list) — a hit BLOCKS + escalates;
2. if the consumer's question was subjective and the draft *answers it with an
   opinion*, BLOCK the opinion and escalate, returning a neutral redirect in
   ``redirected_response`` instead of silently dropping.

A pure redirect (the draft already redirects, or there is no opinion to give)
is allowed. Every trip carries a logged ``reason`` and is suitable for the
audit store; the DB is intentionally NOT wired here.
"""
from __future__ import annotations

import re

from .fair_housing import FairHousingResult, scan_output

# --------------------------------------------------------------------------- #
# Subjective-question detection — DATA. Patterns that mark a neighborhood
# question as opinion-seeking (must be redirected) and the neutral factual
# topics that are always answerable. Extend the tuples to tune coverage.
# --------------------------------------------------------------------------- #

# Opinion-seeking neighborhood signals, grouped by the third-party source the
# redirect should point at. Word-boundary, case-insensitive.
SUBJECTIVE_TOPICS: dict[str, tuple[str, ...]] = {
    "safety": (
        "is it safe", "is this safe", "safe neighborhood", "safe area",
        "safe place", "safe part", "is it dangerous", "dangerous area",
        "how safe", "is the area safe", "feel safe",
    ),
    "schools": (
        "good schools", "great schools", "best schools", "good school district",
        "are the schools good", "how are the schools", "school quality",
        "bad schools", "right schools", "good for school",
    ),
    "crime": (
        "crime rate", "crime rates", "how much crime", "is there crime",
        "high crime", "low crime", "is it a high crime", "crime statistics",
        "how bad is crime",
    ),
    "demographics": (
        "people like me", "people like us", "people like you", "what kind of people",
        "type of people", "who lives", "who lives there", "what's the area like",
        "what is the area like", "is this a good neighborhood for",
        "good neighborhood for people", "is this a", "what nationality",
    ),
    "general_desirability": (
        "good neighborhood", "nice neighborhood", "good area", "nice area",
        "bad neighborhood", "is it a nice", "is it a good", "family-friendly",
        "family friendly", "good place to live", "is it a good place",
    ),
}

# Neutral, objectively answerable topics. Their presence does NOT trigger a
# redirect; a draft answering only these passes the rail.
NEUTRAL_FACTUAL_TOPICS: tuple[str, ...] = (
    "price", "list price", "asking price", "cost", "beds", "bedrooms",
    "baths", "bathrooms", "square feet", "sqft", "square footage", "lot size",
    "year built", "commute", "commute distance", "distance to", "miles to",
    "tax rate", "property tax", "hoa", "hoa fee", "days on market", "acreage",
)

# Third-party redirect targets per subjective topic (neutral, factual sources).
REDIRECT_SOURCES: dict[str, str] = {
    "safety": (
        "I can't offer an opinion on neighborhood safety. For objective data, "
        "please consult public crime data such as the Austin Police Department "
        "crime maps (austintexas.gov/crime) and review HUD's guidance on "
        "evaluating a neighborhood yourself."
    ),
    "schools": (
        "I can't rate schools for you. For objective ratings, see the Texas "
        "Education Agency school report cards (txschools.gov) and review the "
        "individual school district directly."
    ),
    "crime": (
        "I can't characterize crime levels as good or bad. Please review public "
        "crime data such as the Austin Police Department crime maps "
        "(austintexas.gov/crime) and county records to evaluate it yourself."
    ),
    "demographics": (
        "Fair Housing law prevents me from describing who lives in an area or "
        "matching neighborhoods to any group. I can share objective facts "
        "(price, size, taxes, commute) and you can consult HUD resources at "
        "hud.gov to evaluate fit for yourself."
    ),
    "general_desirability": (
        "I can't give an opinion on whether a neighborhood is good, nice, or "
        "family-friendly — that's for you to judge. I can provide objective "
        "facts, and HUD (hud.gov) and local public data sources can help you "
        "evaluate the area yourself."
    ),
}

# Default redirect when a subjective topic has no specific source mapped.
DEFAULT_REDIRECT: str = (
    "I can't answer that with an opinion. I can share objective facts about the "
    "property, and neutral third-party sources (HUD at hud.gov, the Texas "
    "Education Agency, and public crime data) can help you evaluate the "
    "neighborhood yourself."
)

# Opinion verbs/adjectives that mark a *draft* as answering subjectively rather
# than redirecting — used to distinguish "yes, it's very safe" from a redirect.
_OPINION_MARKERS: tuple[str, ...] = (
    "yes", "no", "very", "great", "good", "nice", "safe", "unsafe", "bad",
    "excellent", "wonderful", "definitely", "absolutely", "perfect", "ideal",
    "i'd recommend", "i recommend", "you'll love", "highly", "best", "worst",
)


def _compile(phrases: tuple[str, ...]) -> re.Pattern:
    return re.compile(
        r"\b(" + "|".join(re.escape(p) for p in phrases) + r")\b", re.IGNORECASE
    )


_SUBJECTIVE_RES: dict[str, re.Pattern] = {
    topic: _compile(phrases) for topic, phrases in SUBJECTIVE_TOPICS.items()
}
_NEUTRAL_RE = _compile(NEUTRAL_FACTUAL_TOPICS)
_OPINION_RE = _compile(_OPINION_MARKERS)
# A draft that itself redirects (mentions a neutral source / disclaims opinion)
# is NOT an opinion answer and must not be blocked for "answering".
_REDIRECT_SIGNAL_RE = re.compile(
    r"\b(hud\.gov|hud|can't (offer|give|rate|answer|characterize)|cannot "
    r"(offer|give|rate|answer)|third-party|third party|public crime data|"
    r"txschools|texas education agency|evaluate it yourself|evaluate the "
    r"neighborhood yourself|for you to judge)\b",
    re.IGNORECASE,
)


def detect_subjective_topics(question: str) -> list[str]:
    """Return the subjective neighborhood topics a question asks about.

    Deterministic, DATA-driven. Empty list means the question is not a
    subjective neighborhood question (it may still be a neutral factual one).
    """
    text = question or ""
    return [topic for topic, rx in _SUBJECTIVE_RES.items() if rx.search(text)]


def is_neutral_factual(question: str) -> bool:
    """True if the question asks about an objectively answerable topic only.

    Used to let price/beds/commute/tax questions through. A question that hits
    both a neutral topic and a subjective one is still subjective (the
    subjective part must be redirected).
    """
    text = question or ""
    return bool(_NEUTRAL_RE.search(text)) and not detect_subjective_topics(text)


def build_redirect(topics: list[str]) -> str:
    """Compose a neutral third-party redirect for the given subjective topics."""
    if not topics:
        return DEFAULT_REDIRECT
    # Stable order; one source line per distinct topic.
    parts = [REDIRECT_SOURCES.get(t, DEFAULT_REDIRECT) for t in topics]
    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique = [p for p in parts if not (p in seen or seen.add(p))]
    return " ".join(unique)


def _draft_is_opinion_answer(draft: str) -> bool:
    """True if a draft *answers* (states an opinion) rather than redirecting."""
    text = draft or ""
    if _REDIRECT_SIGNAL_RE.search(text):
        return False
    return bool(_OPINION_RE.search(text))


def review_output(draft: str, *, question: str = "") -> FairHousingResult:
    """The composed Fair Housing OUTPUT gate — call before send.

    Order of checks (most specific block wins):

    1. **Wording deny-list** (:func:`fair_housing.scan_output`): any protected-
       class term or steering proxy in ``draft`` BLOCKS and escalates.
    2. **Subjective-question redirect**: if ``question`` is a subjective
       neighborhood question and ``draft`` answers it with an *opinion*, BLOCK
       the opinion and escalate, returning a neutral third-party redirect in
       ``redirected_response`` (never silently dropped).

    Otherwise the output is allowed: neutral factual answers, and drafts that
    already redirect, pass. The returned :class:`FairHousingResult` is loggable
    to the audit store; the DB is not wired here.
    """
    # 1. Wording rail over the drafted output.
    scan = scan_output(draft)
    if not scan.allowed:
        topics = detect_subjective_topics(question)
        # Attach a safe redirect the orchestrator can send instead of the
        # blocked text, when the consumer's question was itself subjective.
        if topics:
            scan.redirected_response = build_redirect(topics)
        return scan

    # 2. Subjective-question rail: was an opinion given to a subjective Q?
    topics = detect_subjective_topics(question)
    if topics and _draft_is_opinion_answer(draft):
        redirect = build_redirect(topics)
        reason = (
            "fair_housing: BLOCKED — subjective neighborhood question answered "
            f"with an opinion; topics={sorted(topics)}; redirected to neutral "
            "third-party sources (HUD steering guidance)"
        )
        return FairHousingResult(
            allowed=False,
            escalate=True,
            reason=reason,
            redirected_response=redirect,
        )

    # Allowed: clean wording, and no opinion given to a subjective question.
    if topics:
        reason = (
            "fair_housing: PASS — subjective question handled by redirect, no "
            f"opinion asserted; topics={sorted(topics)}"
        )
    else:
        reason = "fair_housing: PASS — neutral factual output, no rail trip"
    return FairHousingResult(allowed=True, escalate=False, reason=reason)
