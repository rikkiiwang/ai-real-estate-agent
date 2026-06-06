# services/brain/tests/test_valuation_market.py
from brain.valuation.market import anchor_and_blend, COMP_HALFLIFE_DAYS
from brain.valuation.model import Prediction
from brain.valuation.schema import CompInput


def _comp(ppsf, sqft=2000.0, age=0, cid="c"):
    return CompInput(id=cid, price=ppsf * sqft, sqft=sqft, age_days=age, address=cid)


def test_anchor_dominates_model_when_comps_present():
    # Model thinks $1,000,000; comps say ~$400k for a 2000 sqft subject.
    pred = Prediction(estimate=1_000_000.0, low=900_000.0, high=1_100_000.0,
                      contributions=[0.0])
    comps = [_comp(200.0, cid="a"), _comp(200.0, cid="b"), _comp(200.0, cid="c")]
    out = anchor_and_blend(pred, subject_sqft=2000.0, comps=comps)
    # ALPHA=0.7 on a $400k anchor pulls the blend far below the model's $1M.
    assert 400_000.0 < out.estimate < 700_000.0
    assert out.low <= out.estimate <= out.high
    # One comp fact per comp, labeled active listing (never "sale").
    kinds = [f.kind for f in out.facts]
    assert kinds.count("comp:active_listing") == 3
    assert all("sale" not in f.description.lower() for f in out.facts)


def test_recent_comps_weighted_higher():
    pred = Prediction(estimate=500_000.0, low=450_000.0, high=550_000.0,
                      contributions=[0.0])
    # A fresh cheap comp and a stale expensive comp; fresh one should pull harder.
    fresh = _comp(150.0, age=0, cid="fresh")
    stale = _comp(350.0, age=4 * COMP_HALFLIFE_DAYS, cid="stale")
    out = anchor_and_blend(pred, subject_sqft=2000.0, comps=[fresh, stale])
    midpoint_ppsf = 250.0 * 2000.0  # unweighted mean would land here
    assert out.estimate < midpoint_ppsf  # weighted toward the fresh, cheaper comp


def test_no_comps_returns_model_estimate_unchanged():
    pred = Prediction(estimate=500_000.0, low=450_000.0, high=550_000.0,
                      contributions=[0.0])
    out = anchor_and_blend(pred, subject_sqft=2000.0, comps=[])
    assert out.estimate == 500_000.0 and out.facts == []


def test_value_record_with_comps_and_freshness():
    from brain.valuation import value_record
    from brain.valuation.features import record_from_features
    from brain.valuation.schema import CompInput

    rec = record_from_features(address="9 Oak", beds=4.0, baths=2.0,
                               sqft=2000.0, year_built=2000)
    comps = [CompInput(id="a", price=400_000.0, sqft=2000.0, age_days=5, address="1 A")]
    v = value_record(rec, comps=comps, as_of="2026-06-05T00:00:00Z",
                     recent_activity="3 new listings in 30d")
    assert v.sufficient_data is True
    assert v.as_of == "2026-06-05T00:00:00Z"
    assert v.recent_activity == "3 new listings in 30d"
    # Carries both the model's feature facts AND the comp facts.
    assert any(f.kind.startswith("feature:") for f in v.facts)
    assert any(f.kind == "comp:active_listing" for f in v.facts)
