"""Composite confidence scoring (U8) — a signal, not a raw token probability.

The Critic (U6) already produces a per-draft ``confidence`` (the mean entailment
score across claims). This module makes the *composite* nature explicit per the
KTD "confidence is a composite signal": it combines three orthogonal signals
derived from a :class:`~brain.lawyer.critic.VerificationResult` into a single
``[0, 1]`` score plus a human-readable reason:

1. **Retrieval coverage** — the fraction of claims that bound a citation (i.e.
   had a retrieved source). A draft built on claims with no provenance is weak
   no matter how the entailer scored the wording.
2. **Critic agreement** — the aggregate entailment signal: the fraction of
   claims the Critic labelled ENTAILED *and* the mean entailment score, blended.
   This is "does the verifier agree the source supports the claim".
3. **Self-consistency** (optional, for HIGH-STAKES claims) — an externally
   supplied agreement fraction across independently sampled generations. When a
   high-stakes flag is set we *require* this input; absent it we fall back to a
   conservative neutral value so a high-stakes draft cannot float up on the
   first two signals alone.

The combination function is defined explicitly below (a weighted geometric-ish
mean — see :func:`composite_confidence`). It is a *severity-aware* blend: a low
coverage signal cannot be fully masked by a high agreement signal.

CALIBRATION CAVEAT (flagged follow-up): this score is **uncalibrated** — the
numbers are an ordinal trust signal, not a probability of correctness, and the
weights are hand-set. Two consequences are baked into the design and the
contract:

* Ops-tunable thresholds compare against this raw score, so a low composite
  escalates — but the *hard* handoff triggers in :mod:`handoff` take precedence
  and fire even at a high composite score.
* Calibrating these weights / mapping the score to an empirical correctness
  probability is a deliberate follow-up (see ``CALIBRATION_FOLLOWUP``), not done
  here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .critic import VerificationResult

# --------------------------------------------------------------------------- #
# Weights for the three composite signals. Hand-set, NOT calibrated. They sum to
# 1.0 so the weighted blend stays in [0, 1]. Coverage and agreement carry the
# bulk; self-consistency is a smaller high-stakes corrective.
# --------------------------------------------------------------------------- #
W_COVERAGE: float = 0.4
W_AGREEMENT: float = 0.4
W_SELF_CONSISTENCY: float = 0.2

# Blend of the two agreement sub-signals (entailed fraction vs mean score).
_ENTAILED_FRACTION_WEIGHT: float = 0.5

# Neutral self-consistency value used when no samples were supplied AND the
# draft is not flagged high-stakes. Deliberately middling so the signal neither
# rewards nor punishes when we simply did not measure it.
NEUTRAL_SELF_CONSISTENCY: float = 0.7

# Conservative fallback when a draft IS flagged high-stakes but self-consistency
# was not measured: we must not let a high-stakes draft float up on coverage +
# agreement alone, so we pull the third signal down.
HIGH_STAKES_MISSING_SELF_CONSISTENCY: float = 0.3

# Flagged follow-up marker (surfaced so callers/audits can assert it exists).
CALIBRATION_FOLLOWUP: str = (
    "UNCALIBRATED: composite confidence weights are hand-set and the score is an "
    "ordinal trust signal, not a probability of correctness. Follow-up: calibrate "
    "weights and map the score to an empirical correctness rate against a labelled "
    "set. Hard handoff triggers (see lawyer.handoff) take precedence over this score."
)


@dataclass(frozen=True)
class ConfidenceSignals:
    """The three orthogonal sub-signals feeding the composite (loggable).

    ``retrieval_coverage`` — fraction of claims with a retrieved source/citation.
    ``critic_agreement`` — aggregate entailment signal (entailed fraction blended
    with mean entailment score). ``self_consistency`` — agreement across sampled
    generations for high-stakes claims (or the neutral/fallback value when not
    measured). ``high_stakes`` records whether the high-stakes path was taken.
    """

    retrieval_coverage: float
    critic_agreement: float
    self_consistency: float
    high_stakes: bool

    def to_dict(self) -> dict:
        """Plain-dict view for the audit store (no DB import here)."""
        return {
            "retrieval_coverage": self.retrieval_coverage,
            "critic_agreement": self.critic_agreement,
            "self_consistency": self.self_consistency,
            "high_stakes": self.high_stakes,
        }


@dataclass(frozen=True)
class ConfidenceScore:
    """A composite confidence score in ``[0, 1]`` plus its reason and signals.

    ``score`` is the uncalibrated composite. ``reason`` explains the value in
    terms of the sub-signals. ``signals`` carries the components for the audit
    log. ``uncalibrated`` is always ``True`` — a standing reminder that this is
    an ordinal trust signal, not a probability (see ``CALIBRATION_FOLLOWUP``).
    """

    score: float
    reason: str
    signals: ConfidenceSignals
    uncalibrated: bool = True

    def to_dict(self) -> dict:
        """Plain-dict view for the audit store."""
        return {
            "score": self.score,
            "reason": self.reason,
            "uncalibrated": self.uncalibrated,
            "signals": self.signals.to_dict(),
            "calibration_followup": CALIBRATION_FOLLOWUP,
        }


def retrieval_coverage(result: VerificationResult) -> float:
    """Fraction of claims that bound a retrieved source (a citation).

    "No source -> no claim" (the Critic's rule) means an uncited claim has no
    provenance; coverage is the share that *did* ground. An empty/claimless
    draft is treated as fully covered (there is nothing ungrounded).
    """
    if not result.claims:
        return 1.0
    cited = sum(1 for v in result.claims if v.citation is not None)
    return cited / len(result.claims)


def critic_agreement(result: VerificationResult) -> float:
    """Aggregate entailment signal from the Critic's per-claim verdicts.

    Blends two views of "the verifier agrees the source supports the claim":
    the fraction of claims labelled ENTAILED, and the mean per-claim entailment
    score. Blending guards against either view alone being gamed — a draft can
    have a high mean score yet a contradicted claim, or all-entailed labels with
    middling scores. An empty draft trivially agrees (1.0).
    """
    if not result.claims:
        return 1.0
    from .entailment import Label  # local import keeps module import-light

    entailed_fraction = sum(
        1 for v in result.claims if v.label is Label.ENTAILED
    ) / len(result.claims)
    mean_score = sum(v.score for v in result.claims) / len(result.claims)
    return (
        _ENTAILED_FRACTION_WEIGHT * entailed_fraction
        + (1.0 - _ENTAILED_FRACTION_WEIGHT) * mean_score
    )


def _resolve_self_consistency(
    self_consistency: Optional[float], *, high_stakes: bool
) -> float:
    """Pick the self-consistency value, applying the high-stakes contract.

    A measured value is used as-is. When none was supplied: a non-high-stakes
    draft gets a neutral value (we simply did not measure it); a high-stakes
    draft gets a conservative low value so it cannot float up unverified.
    """
    if self_consistency is not None:
        return _clamp(self_consistency)
    if high_stakes:
        return HIGH_STAKES_MISSING_SELF_CONSISTENCY
    return NEUTRAL_SELF_CONSISTENCY


def _clamp(x: float) -> float:
    """Clamp a value into ``[0, 1]``."""
    return max(0.0, min(1.0, x))


def composite_confidence(
    result: VerificationResult,
    *,
    self_consistency: Optional[float] = None,
    high_stakes: bool = False,
) -> ConfidenceScore:
    """Combine retrieval coverage, critic agreement, and self-consistency.

    THE COMBINATION FUNCTION (explicit, by design):

        coverage  = fraction of claims with a retrieved source
        agreement = 0.5 * entailed_fraction + 0.5 * mean_entailment_score
        selfcons  = measured value, or neutral/conservative fallback

        weighted  = W_COVERAGE*coverage + W_AGREEMENT*agreement
                    + W_SELF_CONSISTENCY*selfcons          (weights sum to 1)

        # Severity-aware floor: a high agreement signal must NOT fully mask a
        # weak coverage signal. We pull the weighted blend toward the minimum
        # sub-signal so the composite never exceeds halfway between the blend
        # and its weakest component.
        score     = 0.5 * weighted + 0.5 * min(coverage, agreement, selfcons)

    ``high_stakes=True`` requires a self-consistency input; absent one we fall
    back to a conservative value (see :func:`_resolve_self_consistency`).

    The returned :class:`ConfidenceScore` is UNCALIBRATED — see the module
    docstring and ``CALIBRATION_FOLLOWUP``. Hard handoff triggers in
    :mod:`brain.lawyer.handoff` override this score regardless of its value.
    """
    coverage = _clamp(retrieval_coverage(result))
    agreement = _clamp(critic_agreement(result))
    selfcons = _resolve_self_consistency(self_consistency, high_stakes=high_stakes)

    weighted = (
        W_COVERAGE * coverage
        + W_AGREEMENT * agreement
        + W_SELF_CONSISTENCY * selfcons
    )
    weakest = min(coverage, agreement, selfcons)
    score = _clamp(round(0.5 * weighted + 0.5 * weakest, 4))

    signals = ConfidenceSignals(
        retrieval_coverage=round(coverage, 4),
        critic_agreement=round(agreement, 4),
        self_consistency=round(selfcons, 4),
        high_stakes=high_stakes,
    )
    reason = (
        f"composite={score:.2f} (uncalibrated) from "
        f"coverage={coverage:.2f}, agreement={agreement:.2f}, "
        f"self_consistency={selfcons:.2f}"
        + (", high_stakes" if high_stakes else "")
    )
    return ConfidenceScore(score=score, reason=reason, signals=signals)
