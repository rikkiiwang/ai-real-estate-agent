"""U3 AVM tests: real gradient-boosting valuation, honest about coverage.

Covers R1: a known address gets a plausible-band valuation with source-backed
feature facts; the band brackets the estimate; sparse inputs widen the band;
uncovered/empty addresses return insufficient_data (no fabricated number); the
model is deterministic across calls; contributions are exposed as Facts.
"""
from __future__ import annotations

from brain.valuation import Fact, Valuation, estimate_value, value_record
from brain.valuation.features import FEATURE_NAMES, derive_record, is_covered

KNOWN_ADDRESS = "123 Congress Ave, Austin TX"


def test_known_address_returns_plausible_band_with_source_facts() -> None:
    v = estimate_value(KNOWN_ADDRESS)
    assert isinstance(v, Valuation)
    assert v.sufficient_data is True
    # Plausible Austin single-family band, not a degenerate number.
    assert 40_000 < v.estimate < 5_000_000
    assert len(v.facts) >= 1
    assert all(isinstance(f, Fact) for f in v.facts)
    # Every fact cites a source and a feature kind (for the Critic to bind).
    assert all(f.source_id for f in v.facts)
    assert all(f.kind.startswith("feature:") for f in v.facts)


def test_band_brackets_the_estimate() -> None:
    v = estimate_value(KNOWN_ADDRESS)
    assert v.low <= v.estimate <= v.high
    assert v.low > 0
    assert v.high > v.low  # a real interval, not a collapsed point


def test_feature_contributions_exposed_as_facts() -> None:
    v = estimate_value(KNOWN_ADDRESS)
    # One fact per modeled feature, aligned to the fixed feature order.
    kinds = [f.kind for f in v.facts]
    assert kinds == [f"feature:{name}" for name in FEATURE_NAMES]
    # At least one feature has a non-trivial dollar contribution.
    assert any(abs(f.contribution) > 1.0 for f in v.facts)


def test_uncovered_address_returns_insufficient_data() -> None:
    for addr in ("", "   ", "123 Unknown St, Nowhere"):
        v = estimate_value(addr)
        assert v.sufficient_data is False, addr
        assert v.estimate == 0
        assert v.low == 0 and v.high == 0
        assert v.facts == []  # no fabricated facts for an uncovered address


def test_is_covered_contract() -> None:
    assert is_covered(KNOWN_ADDRESS) is True
    assert is_covered("") is False
    assert is_covered("   ") is False
    assert is_covered("a place with no coverage") is False


def test_model_is_deterministic_across_calls() -> None:
    a = estimate_value(KNOWN_ADDRESS)
    b = estimate_value(KNOWN_ADDRESS)
    assert a == b
    # Whitespace/case-normalized address resolves to the same valuation.
    c = estimate_value("  123  congress ave, austin tx ")
    assert c.estimate == a.estimate
    assert c.low == a.low and c.high == a.high


def test_sparse_input_widens_band_vs_known_condition() -> None:
    # Same address, but supply a photo-derived condition signal: the band should
    # be no wider (we add sparse widening only when the signal is missing).
    sparse = estimate_value(KNOWN_ADDRESS)  # no condition -> imputed -> widened
    record = derive_record(KNOWN_ADDRESS, condition=0.5)
    assert record is not None
    dense = value_record(record)

    sparse_width = sparse.high - sparse.low
    dense_width = dense.high - dense.low
    assert sparse_width > dense_width
    # The sparse case marks its condition fact as imputed; the dense one does not.
    sparse_condition = next(f for f in sparse.facts if f.kind == "feature:condition")
    dense_condition = next(f for f in dense.facts if f.kind == "feature:condition")
    assert "imputed" in sparse_condition.description
    assert "imputed" not in dense_condition.description


def test_condition_signal_moves_the_estimate() -> None:
    # Higher photo-derived condition should not value below lower condition.
    low_cond = value_record(derive_record(KNOWN_ADDRESS, condition=0.1))  # type: ignore[arg-type]
    high_cond = value_record(derive_record(KNOWN_ADDRESS, condition=0.9))  # type: ignore[arg-type]
    assert high_cond.estimate >= low_cond.estimate
