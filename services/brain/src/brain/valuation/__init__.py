"""Valuation core (the "Brain") — a real gradient-boosting AVM.

``estimate_value(address)`` derives a deterministic, normalized property record
for the address, runs it through a synthetic-trained gradient-boosting AVM, and
returns a :class:`Valuation` with a point estimate, an uncertainty band, and
source-backed :class:`Fact` feature contributions for the Critic to cite.

Honesty over precision: an address with no ingested coverage (blank or an
explicitly-uncovered marker) returns ``sufficient_data=False`` with no number,
and sparse inputs (e.g. no photo-derived condition) widen the band rather than
asserting false precision. The public ``estimate_value`` / ``Valuation`` / ``Fact``
shapes are the stable contract consumed by ``brain.server``.
"""
from __future__ import annotations

from typing import Optional

from . import features as _features
from .model import get_model
from .schema import Fact, PropertyRecord, Valuation

__all__ = [
    "Fact",
    "Valuation",
    "PropertyRecord",
    "estimate_value",
    "value_record",
]

# Human-readable descriptions for each feature, used when citing contributions.
_FEATURE_DESCRIPTIONS: dict[str, str] = {
    "beds": "Bedroom count",
    "baths": "Bathroom count",
    "sqft": "Living area (sqft)",
    "lot_sqft": "Lot size (sqft)",
    "age": "Property age (years)",
    "garage_spaces": "Garage spaces",
    "dist_to_center_km": "Distance to city center (km)",
    "condition": "Photo-derived condition score",
}


def _facts_from_contributions(
    record: PropertyRecord,
    contributions: list[float],
    *,
    imputed_condition: bool,
) -> list[Fact]:
    """Build source-cited :class:`Fact`s from per-feature dollar contributions.

    Each feature is tied to the record's backing source ids so the Critic can
    bind the cited contribution to a source. Imputed (missing) signals are
    labeled as such so a downstream consumer can see what was inferred.
    """
    primary_source = record.source_ids[0] if record.source_ids else "derived"
    facts: list[Fact] = []
    for name, contribution in zip(_features.FEATURE_NAMES, contributions):
        description = _FEATURE_DESCRIPTIONS.get(name, name)
        if name == "condition" and imputed_condition:
            description += " (imputed: no photo signal)"
            source_id = "derived:condition_default"
        else:
            source_id = primary_source
        facts.append(
            Fact(
                source_id=source_id,
                kind=f"feature:{name}",
                description=description,
                contribution=round(float(contribution), 2),
            )
        )
    return facts


def value_record(record: PropertyRecord) -> Valuation:
    """Value a normalized :class:`PropertyRecord` with the AVM.

    Exposed for U2/U5 to call once the real ingestion join produces records
    directly, without going through address-derivation.
    """
    model = get_model()
    imputed_condition = record.condition is None
    sparse_signals = 1 if imputed_condition else 0

    vector = _features.feature_vector(record)
    prediction = model.predict(vector, sparse_signals=sparse_signals)

    facts = _facts_from_contributions(
        record, prediction.contributions, imputed_condition=imputed_condition
    )
    return Valuation(
        sufficient_data=True,
        estimate=round(prediction.estimate, 2),
        low=round(prediction.low, 2),
        high=round(prediction.high, 2),
        facts=facts,
    )


def estimate_value(address: str, *, condition: Optional[float] = None) -> Valuation:
    """Return a source-cited AVM valuation for ``address``.

    ``condition`` is the optional photo-derived condition score in ``[0, 1]``
    (U4's vision output, injected by the orchestrator — never imported here).
    Addresses with no ingested coverage return ``sufficient_data=False``.
    """
    record = _features.derive_record(address, condition=condition)
    if record is None:
        return Valuation(sufficient_data=False)
    return value_record(record)
