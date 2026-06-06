# Real-Time Valuation (PRD R3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn valuation from a synthetic-trained model fed address-hash features into a genuinely data-grounded, freshness-aware estimate: value a home from its REAL attributes, anchored on REAL comparable listings from our DB, with an honest "as of <time>" + recent-activity summary, every number cited.

**Architecture:** The brain keeps the sklearn AVM but gains a market layer — when given real features + comps it anchors the estimate on a recency-weighted comp price-per-sqft and blends the model in (comps dominant), returning comp citations + freshness. Rails owns the data: a `CompsSelector` picks comps from the `Property` pool, `MarketActivity` computes freshness from `MarketSnapshot`, a `ValuationAssembly` service wires subject-attributes + comps + recency into the existing `GetValuation` gRPC. Request path reads cache only; a capped pre-warm task is the only thing that ever calls RentCast.

**Tech Stack:** Python (brain, sklearn, grpc_tools), protobuf, Rails 8.1 (domain, SQLite tests), Minitest, pytest.

**Spec:** `docs/superpowers/specs/2026-06-06-brain-realtime-valuation-design.md`

**Quota discipline (non-negotiable):** Parts A–C spend **zero** RentCast calls (they use already-imported `Property` data). Only Part D calls RentCast, and only through a capped, cache-first pre-warm task. The live site / demo never calls RentCast.

---

## File Structure

**Brain (Python) — `services/brain/src/brain/valuation/`**
- `market.py` (NEW) — comp anchoring + blend + comp/market facts. One job: turn (model prediction, subject record, comps, freshness) into a market-grounded `Valuation`.
- `features.py` (MODIFY) — add `record_from_features(...)` to build a `PropertyRecord` from real attributes (sibling to the existing hash `derive_record`).
- `schema.py` (MODIFY) — add `CompInput` dataclass; add `as_of` + `recent_activity` to `Valuation`.
- `__init__.py` (MODIFY) — extend `value_record(record, comps=None, as_of=None, recent_activity=None)`.
- `server.py` (MODIFY) — `GetValuation` uses the real-features path when the request carries features.

**Proto — `proto/realestate/v1/realestate.proto`** (MODIFY) — `PropertyFeatures`, `CompInput` messages; extend `GetValuationRequest` + `GetValuationResponse`.

**Rails (`services/domain/`)**
- `app/services/comps_selector.rb` (NEW) — pick K recency/similarity-weighted comps from `Property.browsable`.
- `app/services/market_activity.rb` (NEW) — "as of" + recent-activity summary from `MarketSnapshot` + `Property`.
- `app/services/subject_resolver.rb` (NEW) — resolve a subject's real attributes (existing `Property`, else `PropertyRecordCache`, else nil).
- `app/services/valuation_assembly.rb` (NEW) — orchestrates resolver + comps + activity → `BrainValuationClient`. Shared by seller + buyer paths.
- `app/services/brain_valuation_client.rb` (MODIFY) — send features + comps + recency; map `as_of`/`recent_activity`.
- `app/models/property_record_cache.rb` (NEW, Part D) — per-address real attrs + tax cache.
- `app/services/rent_cast_client.rb` (MODIFY, Part D) — `property_record(address)`.
- `lib/tasks/rentcast.rake` (MODIFY, Part D) — capped `rentcast:prewarm` task.
- `app/controllers/seller/valuations_controller.rb` + `app/views/seller/valuations/create.html.erb` (MODIFY) — use assembly, surface freshness/comps.
- `app/views/agent/messages/_price_check.html.erb` (MODIFY) — surface freshness/comps in the sidebar.

---

# PART A — Brain: real-features valuation, comp anchoring, freshness

### Task A1: `record_from_features` — build a PropertyRecord from real attributes

**Files:**
- Modify: `services/brain/src/brain/valuation/features.py`
- Test: `services/brain/tests/test_valuation_real_features.py` (NEW)

- [ ] **Step 1: Write the failing test**

```python
# services/brain/tests/test_valuation_real_features.py
from brain.valuation import features as feat
from brain.valuation.schema import PropertyRecord


def test_record_from_features_uses_real_values_not_hash():
    rec = feat.record_from_features(
        address="123 Real St, Austin, TX 78704",
        beds=4.0, baths=2.5, sqft=2200.0, lot_sqft=6500.0,
        year_built=1998, latitude=30.245, longitude=-97.77,
        garage_spaces=2.0, condition=None,
    )
    assert isinstance(rec, PropertyRecord)
    assert rec.beds == 4.0 and rec.baths == 2.5 and rec.sqft == 2200.0
    assert rec.year_built == 1998
    assert rec.latitude == 30.245 and rec.longitude == -97.77
    # Provenance points at the listing feed, not a derived hash parcel.
    assert any("listing" in s for s in rec.source_ids)


def test_record_from_features_defaults_missing_geo_to_city_center():
    rec = feat.record_from_features(
        address="x", beds=3.0, baths=2.0, sqft=1500.0, lot_sqft=None,
        year_built=None, latitude=None, longitude=None,
        garage_spaces=None, condition=None,
    )
    # Missing lot/year/geo fall back to neutral defaults so the vector is valid.
    assert rec.latitude == feat._LAT_CENTER and rec.longitude == feat._LON_CENTER
    assert rec.lot_sqft > 0 and rec.year_built >= 1900
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/brain && python3 -m pytest tests/test_valuation_real_features.py -v`
Expected: FAIL with `AttributeError: module 'brain.valuation.features' has no attribute 'record_from_features'`

- [ ] **Step 3: Implement `record_from_features`**

Add to `services/brain/src/brain/valuation/features.py` (after `derive_record`):

```python
# Neutral fallbacks when a real listing omits a field (kept honest: a missing
# lot/year widens nothing here — the band already widens on sparse condition).
_DEFAULT_LOT_SQFT: float = 6000.0
_DEFAULT_YEAR_BUILT: int = 1990


def record_from_features(
    address: str,
    *,
    beds: float,
    baths: float,
    sqft: float,
    lot_sqft: Optional[float] = None,
    year_built: Optional[int] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    garage_spaces: Optional[float] = None,
    condition: Optional[float] = None,
) -> PropertyRecord:
    """Build a :class:`PropertyRecord` from REAL listing/record attributes.

    Sibling to :func:`derive_record` (which hashes the address). This is the
    path used once the Rails ingestion join supplies a subject's true beds/
    baths/sqft/geo, so the AVM reasons over real data rather than a hash.
    Missing optional fields fall back to neutral defaults so the fixed-order
    feature vector is always valid.
    """
    if condition is not None:
        condition = max(0.0, min(1.0, float(condition)))
    return PropertyRecord(
        address=(address or "").strip(),
        beds=float(beds),
        baths=float(baths),
        sqft=float(sqft),
        lot_sqft=float(lot_sqft) if lot_sqft else _DEFAULT_LOT_SQFT,
        year_built=int(year_built) if year_built else _DEFAULT_YEAR_BUILT,
        latitude=float(latitude) if latitude is not None else _LAT_CENTER,
        longitude=float(longitude) if longitude is not None else _LON_CENTER,
        garage_spaces=float(garage_spaces) if garage_spaces else 0.0,
        condition=condition,
        source_ids=("listing:rentcast",),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/brain && python3 -m pytest tests/test_valuation_real_features.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add services/brain/src/brain/valuation/features.py services/brain/tests/test_valuation_real_features.py
git commit -m "feat(brain): build PropertyRecord from real attributes (record_from_features)"
```

---

### Task A2: `CompInput` schema + `as_of`/`recent_activity` on Valuation

**Files:**
- Modify: `services/brain/src/brain/valuation/schema.py`
- Test: `services/brain/tests/test_valuation_real_features.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
def test_comp_input_and_valuation_freshness_fields():
    from brain.valuation.schema import CompInput, Valuation
    c = CompInput(id="p1", price=500_000.0, sqft=2000.0, beds=4.0, baths=2.0,
                  distance_mi=0.4, age_days=12, address="1 A St")
    assert c.price_per_sqft == 250.0
    v = Valuation(sufficient_data=True, estimate=1.0,
                  as_of="2026-06-05T00:00:00Z", recent_activity="3 new in 30d")
    assert v.as_of == "2026-06-05T00:00:00Z"
    assert v.recent_activity == "3 new in 30d"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/brain && python3 -m pytest tests/test_valuation_real_features.py::test_comp_input_and_valuation_freshness_fields -v`
Expected: FAIL with `ImportError: cannot import name 'CompInput'`

- [ ] **Step 3: Implement**

In `services/brain/src/brain/valuation/schema.py`, add to the `Valuation` dataclass (after `facts`):

```python
    # Freshness metadata (set on the comps-grounded path; None on hash fallback).
    as_of: Optional[str] = None
    recent_activity: Optional[str] = None
```

And append a new dataclass:

```python
@dataclass(frozen=True)
class CompInput:
    """A real comparable listing passed in by Rails to anchor the estimate.

    These are ACTIVE listings (asking prices), never described as closed sales.
    """

    id: str
    price: float
    sqft: float
    beds: float = 0.0
    baths: float = 0.0
    distance_mi: float = 0.0
    age_days: int = 0
    address: str = ""

    @property
    def price_per_sqft(self) -> float:
        return self.price / self.sqft if self.sqft > 0 else 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/brain && python3 -m pytest tests/test_valuation_real_features.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add services/brain/src/brain/valuation/schema.py services/brain/tests/test_valuation_real_features.py
git commit -m "feat(brain): CompInput schema + freshness fields on Valuation"
```

---

### Task A3: `market.py` — recency-weighted comp anchor + blend

**Files:**
- Create: `services/brain/src/brain/valuation/market.py`
- Test: `services/brain/tests/test_valuation_market.py` (NEW)

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/brain && python3 -m pytest tests/test_valuation_market.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'brain.valuation.market'`

- [ ] **Step 3: Implement `market.py`**

```python
# services/brain/src/brain/valuation/market.py
"""Market grounding for the AVM: anchor the estimate on real comps.

Given the model's prediction and a set of REAL comparable ACTIVE listings, this
computes a recency-weighted comp price-per-sqft anchor and blends it with the
model (comps dominant), so the final number reflects the live local market while
the model still contributes structure and the explainable per-feature drivers.
Comps are active listings (asking prices) and are labeled as such — never sales.
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import Prediction
from .schema import CompInput, Fact

# Weight of the comp anchor in the blend (comps dominate; model adds structure).
COMP_ANCHOR_ALPHA: float = 0.7
# Half-life (days) for recency weighting a comp's influence.
COMP_HALFLIFE_DAYS: float = 30.0


@dataclass
class MarketResult:
    estimate: float
    low: float
    high: float
    facts: list[Fact]


def _recency_weight(age_days: int) -> float:
    return 0.5 ** (max(0, age_days) / COMP_HALFLIFE_DAYS)


def anchor_and_blend(
    prediction: Prediction,
    *,
    subject_sqft: float,
    comps: list[CompInput],
) -> MarketResult:
    """Blend the model prediction with a recency-weighted comp anchor."""
    usable = [c for c in comps if c.sqft > 0 and c.price > 0]
    if not usable or subject_sqft <= 0:
        return MarketResult(
            estimate=prediction.estimate, low=prediction.low,
            high=prediction.high, facts=[],
        )

    weights = [_recency_weight(c.age_days) for c in usable]
    wsum = sum(weights) or 1.0
    anchor_ppsf = sum(w * c.price_per_sqft for w, c in zip(weights, usable)) / wsum
    comp_anchor = anchor_ppsf * subject_sqft

    estimate = COMP_ANCHOR_ALPHA * comp_anchor + (1.0 - COMP_ANCHOR_ALPHA) * prediction.estimate

    # Band: union the model band with the comp dispersion (implied subject prices).
    implied = sorted(c.price_per_sqft * subject_sqft for c in usable)
    low = min(prediction.low, implied[0], estimate)
    high = max(prediction.high, implied[-1], estimate)
    low = max(0.0, low)

    facts = [
        Fact(
            source_id=f"comp:{c.id}",
            kind="comp:active_listing",
            description=(
                f"Active listing {c.address}: ${c.price:,.0f} "
                f"(${c.price_per_sqft:,.0f}/sqft, {c.distance_mi:.1f} mi, "
                f"listed {c.age_days}d ago)"
            ),
            contribution=0.0,
        )
        for c in usable
    ]
    return MarketResult(estimate=round(estimate, 2), low=round(low, 2),
                        high=round(high, 2), facts=facts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/brain && python3 -m pytest tests/test_valuation_market.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add services/brain/src/brain/valuation/market.py services/brain/tests/test_valuation_market.py
git commit -m "feat(brain): recency-weighted comp anchor + blend (market.py)"
```

---

### Task A4: extend `value_record` to accept comps + freshness

**Files:**
- Modify: `services/brain/src/brain/valuation/__init__.py`
- Test: `services/brain/tests/test_valuation_market.py` (append)

- [ ] **Step 1: Write the failing test (append)**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/brain && python3 -m pytest tests/test_valuation_market.py::test_value_record_with_comps_and_freshness -v`
Expected: FAIL with `TypeError: value_record() got an unexpected keyword argument 'comps'`

- [ ] **Step 3: Implement**

In `services/brain/src/brain/valuation/__init__.py`, update imports and `value_record`:

```python
from .market import anchor_and_blend
from .schema import CompInput, Fact, PropertyRecord, Valuation
```

Add `"CompInput"` to `__all__`. Replace `value_record` with:

```python
def value_record(
    record: PropertyRecord,
    *,
    comps: Optional[list["CompInput"]] = None,
    as_of: Optional[str] = None,
    recent_activity: Optional[str] = None,
) -> Valuation:
    """Value a normalized :class:`PropertyRecord` with the AVM.

    When ``comps`` are supplied the estimate is anchored on the recency-weighted
    comp price-per-sqft (comps dominant) and the comp citations are attached;
    ``as_of`` / ``recent_activity`` carry honest freshness metadata through.
    """
    model = get_model()
    imputed_condition = record.condition is None
    sparse_signals = 1 if imputed_condition else 0

    vector = _features.feature_vector(record)
    prediction = model.predict(vector, sparse_signals=sparse_signals)

    facts = _facts_from_contributions(
        record, prediction.contributions, imputed_condition=imputed_condition
    )

    estimate, low, high = prediction.estimate, prediction.low, prediction.high
    if comps:
        market = anchor_and_blend(prediction, subject_sqft=record.sqft, comps=comps)
        estimate, low, high = market.estimate, market.low, market.high
        facts = facts + market.facts

    return Valuation(
        sufficient_data=True,
        estimate=round(estimate, 2),
        low=round(low, 2),
        high=round(high, 2),
        facts=facts,
        as_of=as_of,
        recent_activity=recent_activity,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/brain && python3 -m pytest tests/test_valuation_market.py tests/test_valuation_avm.py -v`
Expected: PASS (existing AVM tests still green; new test passes)

- [ ] **Step 5: Commit**

```bash
git add services/brain/src/brain/valuation/__init__.py services/brain/tests/test_valuation_market.py
git commit -m "feat(brain): value_record accepts comps + freshness metadata"
```

---

### Task A5: extend the proto contract

**Files:**
- Modify: `proto/realestate/v1/realestate.proto`
- Regenerate: all language stubs via `make proto`

- [ ] **Step 1: Edit the proto**

In `proto/realestate/v1/realestate.proto`, replace the `GetValuationRequest` message and add two new messages above it; extend `GetValuationResponse`:

```proto
message PropertyFeatures {
  double beds = 1;
  double baths = 2;
  double sqft = 3;
  double lot_sqft = 4;
  int32 year_built = 5;
  double latitude = 6;
  double longitude = 7;
  double garage_spaces = 8;
  double condition = 9;       // photo-derived [0,1]; 0 with has_condition=false means unknown
  bool has_condition = 10;
}

message CompInput {
  string id = 1;
  double price = 2;
  double sqft = 3;
  double beds = 4;
  double baths = 5;
  double distance_mi = 6;
  int32 age_days = 7;
  string address = 8;
}

message GetValuationRequest {
  string address = 1;
  PropertyFeatures features = 2;   // optional; absent => address-hash fallback
  repeated CompInput comps = 3;    // optional; empty => model-only
  string as_of = 4;                // optional freshness label (ISO 8601)
  string recent_activity = 5;      // optional human-readable recent-activity summary
}
```

Add two fields to `GetValuationResponse` (after `facts`):

```proto
  string as_of = 6;            // echoed freshness label
  string recent_activity = 7;  // echoed recent-activity summary
```

- [ ] **Step 2: Regenerate stubs**

Run: `make proto`
Expected: regenerates Go (`proto/gen/go`), Python (`services/brain/src/genproto`), and Ruby (`services/domain`) stubs with no protoc errors.

- [ ] **Step 3: Verify the generated symbols exist**

Run: `cd services/brain && python3 -c "from genproto.realestate.v1 import realestate_pb2 as pb; print(pb.PropertyFeatures, pb.CompInput); r=pb.GetValuationRequest(); print(r.DESCRIPTOR.fields_by_name.keys())"`
Expected: prints the two message types and a field list including `address, features, comps, as_of, recent_activity`.

- [ ] **Step 4: Commit**

```bash
git add proto/ services/brain/src/genproto services/domain
git commit -m "feat(proto): GetValuation carries real features, comps, freshness"
```

---

### Task A6: wire the real-features path into the `GetValuation` servicer

**Files:**
- Modify: `services/brain/src/brain/server.py:24-36`
- Test: `services/brain/tests/test_valuation_roundtrip.py` (append)

- [ ] **Step 1: Write the failing test (append)**

Open `services/brain/tests/test_valuation_roundtrip.py`, note the existing helper that builds a `ValuationServicer` + request, and append:

```python
def test_getvaluation_real_features_path_anchors_on_comps():
    from genproto.realestate.v1 import realestate_pb2 as pb
    from brain.server import ValuationServicer

    req = pb.GetValuationRequest(
        address="9 Oak St, Austin, TX 78704",
        features=pb.PropertyFeatures(beds=4, baths=2, sqft=2000, year_built=2000,
                                     latitude=30.24, longitude=-97.77),
        comps=[pb.CompInput(id="a", price=400000, sqft=2000, age_days=5, address="1 A St")],
        as_of="2026-06-05T00:00:00Z",
        recent_activity="3 new listings in 30d",
    )
    resp = ValuationServicer().GetValuation(req, None)
    assert resp.sufficient_data is True
    assert resp.as_of == "2026-06-05T00:00:00Z"
    assert resp.recent_activity == "3 new listings in 30d"
    assert any(f.kind == "comp:active_listing" for f in resp.facts)
    # $400k comp anchor pulls the estimate well under the model's synthetic level.
    assert 350_000 < resp.estimate < 750_000


def test_getvaluation_address_only_still_works():
    from genproto.realestate.v1 import realestate_pb2 as pb
    from brain.server import ValuationServicer
    resp = ValuationServicer().GetValuation(pb.GetValuationRequest(address="5 Elm St"), None)
    assert resp.sufficient_data is True
    assert resp.as_of == ""  # no freshness on the hash-fallback path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/brain && python3 -m pytest tests/test_valuation_roundtrip.py::test_getvaluation_real_features_path_anchors_on_comps -v`
Expected: FAIL (estimate not anchored / `as_of` empty — current servicer ignores features).

- [ ] **Step 3: Implement**

Replace the body of `GetValuation` in `services/brain/src/brain/server.py`:

```python
class ValuationServicer(rpc.ValuationServicer):
    def GetValuation(self, request, context):
        v = self._value(request)
        return pb.GetValuationResponse(
            sufficient_data=v.sufficient_data,
            estimate=v.estimate,
            low=v.low,
            high=v.high,
            facts=[
                pb.SourceFact(source_id=f.source_id, kind=f.kind,
                              description=f.description, contribution=f.contribution)
                for f in v.facts
            ],
            as_of=v.as_of or "",
            recent_activity=v.recent_activity or "",
        )

    @staticmethod
    def _value(request):
        if request.HasField("features"):
            from brain.valuation import value_record
            from brain.valuation.features import record_from_features
            from brain.valuation.schema import CompInput
            f = request.features
            record = record_from_features(
                address=request.address,
                beds=f.beds, baths=f.baths, sqft=f.sqft, lot_sqft=f.lot_sqft,
                year_built=f.year_built or None,
                latitude=f.latitude or None, longitude=f.longitude or None,
                garage_spaces=f.garage_spaces or None,
                condition=f.condition if f.has_condition else None,
            )
            comps = [
                CompInput(id=c.id, price=c.price, sqft=c.sqft, beds=c.beds,
                          baths=c.baths, distance_mi=c.distance_mi,
                          age_days=c.age_days, address=c.address)
                for c in request.comps
            ]
            return value_record(record, comps=comps or None,
                                as_of=request.as_of or None,
                                recent_activity=request.recent_activity or None)
        return estimate_value(request.address)
```

Keep the existing `from brain.valuation import estimate_value` import at the top.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/brain && python3 -m pytest tests/test_valuation_roundtrip.py -v`
Expected: PASS (both new tests + existing ones)

- [ ] **Step 5: Run the full brain suite**

Run: `cd services/brain && python3 -m pytest -q`
Expected: all pass (no regressions).

- [ ] **Step 6: Commit**

```bash
git add services/brain/src/brain/server.py services/brain/tests/test_valuation_roundtrip.py
git commit -m "feat(brain): GetValuation uses real features + comps when provided"
```

---

# PART B — Rails: comp selection, market activity, subject resolution

> All of Part B reads only the existing `Property` / `MarketSnapshot` tables. Zero RentCast calls.

### Task B1: `CompsSelector` — pick recency/similarity-weighted comps from the pool

**Files:**
- Create: `services/domain/app/services/comps_selector.rb`
- Test: `services/domain/test/services/comps_selector_test.rb` (NEW)

- [ ] **Step 1: Write the failing test**

```ruby
# services/domain/test/services/comps_selector_test.rb
require "test_helper"

class CompsSelectorTest < ActiveSupport::TestCase
  def listing(addr:, region:, price:, sqft:, beds: 3, captured: Time.current)
    Property.create!(address: addr, state: "listed", region: region,
                     list_price: price, sqft: sqft, beds: beds, baths: 2,
                     source_name: "RentCast (live listing data)", captured_at: captured)
  end

  test "selects same-region browsable listings, excludes the subject itself" do
    subject = listing(addr: "1 Oak St", region: "Austin 78704", price: 500_000, sqft: 2000)
    listing(addr: "2 Oak St", region: "Austin 78704", price: 520_000, sqft: 2050)
    listing(addr: "9 Far Ave", region: "Austin 78759", price: 900_000, sqft: 2100)

    comps = CompsSelector.new(region: "Austin 78704", exclude_address: "1 Oak St").call(limit: 5)

    addrs = comps.map(&:address)
    assert_includes addrs, "2 Oak St"
    refute_includes addrs, "1 Oak St"      # subject excluded
    refute_includes addrs, "9 Far Ave"     # different region excluded
  end

  test "excludes retired and price-less listings, returns CompInput-shaped structs" do
    listing(addr: "2 Oak St", region: "Austin 78704", price: 520_000, sqft: 2050)
    Property.create!(address: "3 Oak St", state: "listed", region: "Austin 78704",
                     list_price: 500_000, sqft: 2000, retired_at: Time.current,
                     source_name: "RentCast (live listing data)", captured_at: Time.current)

    comps = CompsSelector.new(region: "Austin 78704", exclude_address: "1 Oak St").call(limit: 5)

    assert_equal ["2 Oak St"], comps.map(&:address)
    c = comps.first
    assert_equal 520_000.0, c.price
    assert_equal 2050, c.sqft
    assert c.age_days >= 0
  end

  test "limit caps the number returned" do
    6.times { |i| listing(addr: "#{i} Oak St", region: "Austin 78704", price: 500_000 + i, sqft: 2000) }
    comps = CompsSelector.new(region: "Austin 78704", exclude_address: "z").call(limit: 4)
    assert_equal 4, comps.size
  end
end
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/domain && bin/rails test test/services/comps_selector_test.rb`
Expected: FAIL with `uninitialized constant CompsSelector`

- [ ] **Step 3: Implement**

```ruby
# services/domain/app/services/comps_selector.rb
# Picks comparable ACTIVE listings for a subject from the cached Property pool.
# Reads only the DB (never RentCast). Comps are asking-price active listings —
# the brain labels them as such, never as closed sales. Ranked by similarity
# (price-per-sqft proximity is handled downstream by recency weighting; here we
# pick the freshest, closest-in-size same-region listings).
class CompsSelector
  Comp = Struct.new(:id, :address, :price, :sqft, :beds, :baths, :distance_mi,
                    :age_days, keyword_init: true)

  def initialize(region:, exclude_address: nil, subject_sqft: nil)
    @region = region
    @exclude_address = exclude_address.to_s.strip.downcase
    @subject_sqft = subject_sqft
  end

  def call(limit: 5)
    scope = Property.browsable.where(region: @region).where.not(sqft: nil)
    rows = scope.reject { |p| p.address.to_s.strip.downcase == @exclude_address }
    rows = rows.sort_by { |p| size_gap(p) }.first(limit)
    rows.map { |p| to_comp(p) }
  end

  private

  def size_gap(property)
    return 0 if @subject_sqft.blank? || property.sqft.blank?
    (property.sqft - @subject_sqft).abs
  end

  def to_comp(property)
    Comp.new(
      id: property.id.to_s,
      address: property.address,
      price: property.list_price.to_f,
      sqft: property.sqft.to_i,
      beds: property.beds.to_i,
      baths: property.baths.to_f,
      distance_mi: 0.0, # same-region proxy; refined when subject geo is known
      age_days: age_days_for(property),
    )
  end

  def age_days_for(property)
    return 0 if property.captured_at.blank?
    ((Time.current - property.captured_at) / 1.day).floor
  end
end
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/domain && bin/rails test test/services/comps_selector_test.rb`
Expected: PASS (3 runs, 0 failures)

- [ ] **Step 5: Commit**

```bash
git add services/domain/app/services/comps_selector.rb services/domain/test/services/comps_selector_test.rb
git commit -m "feat(domain): CompsSelector picks comps from the cached listing pool"
```

---

### Task B2: `MarketActivity` — honest "as of" + recent-activity summary

**Files:**
- Create: `services/domain/app/services/market_activity.rb`
- Test: `services/domain/test/services/market_activity_test.rb` (NEW)

- [ ] **Step 1: Write the failing test**

```ruby
# services/domain/test/services/market_activity_test.rb
require "test_helper"

class MarketActivityTest < ActiveSupport::TestCase
  test "summarizes new listings and as_of from the ZIP snapshot" do
    MarketSnapshot.create!(zip: "78704", area: "Austin 78704", median_price: 600_000,
                           avg_price_per_sqft: 320, new_listings: 3,
                           avg_days_on_market: 21, as_of: Date.new(2026, 6, 5))

    a = MarketActivity.new(region: "Austin 78704").call

    assert_equal Date.new(2026, 6, 5), a.as_of.to_date
    assert_match(/3 new listing/, a.summary)
    assert_match(/21/, a.summary) # days on market surfaced
  end

  test "honest empty summary when no snapshot exists" do
    a = MarketActivity.new(region: "Austin 99999").call
    assert_nil a.as_of
    assert_match(/no recent market data/i, a.summary)
  end
end
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/domain && bin/rails test test/services/market_activity_test.rb`
Expected: FAIL with `uninitialized constant MarketActivity`

- [ ] **Step 3: Implement**

```ruby
# services/domain/app/services/market_activity.rb
# Computes an HONEST freshness label + recent-activity summary for a region from
# the cached MarketSnapshot (per-ZIP RentCast sale stats). No fabricated live
# stream: when there's no snapshot it says so. Reads only the DB.
class MarketActivity
  Result = Struct.new(:as_of, :summary, keyword_init: true)

  def initialize(region:)
    @region = region
    @zip = region.to_s[/\d{5}/]
  end

  def call
    snap = @zip && MarketSnapshot.find_by(zip: @zip)
    return Result.new(as_of: nil, summary: "No recent market data for this area.") unless snap

    parts = []
    parts << "#{snap.new_listings} new listing#{'s' unless snap.new_listings == 1} recently" if snap.new_listings.present?
    parts << "median $#{snap.median_price.to_i.to_s(:delimited)}" if snap.median_price.present?
    parts << "avg #{snap.avg_days_on_market.to_i} days on market" if snap.avg_days_on_market.present?
    summary = parts.any? ? parts.join(" · ") : "Market snapshot available."
    Result.new(as_of: snap.as_of, summary: summary)
  end
end
```

> Note: if `to_s(:delimited)` is unavailable in this Rails version, the test only asserts on `new_listings` and `avg_days_on_market`; swap to `ActiveSupport::NumberHelper.number_to_delimited(snap.median_price.to_i)` if the suite flags it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/domain && bin/rails test test/services/market_activity_test.rb`
Expected: PASS (2 runs, 0 failures)

- [ ] **Step 5: Commit**

```bash
git add services/domain/app/services/market_activity.rb services/domain/test/services/market_activity_test.rb
git commit -m "feat(domain): MarketActivity honest freshness + recent-activity summary"
```

---

### Task B3: `SubjectResolver` — resolve a subject's real attributes from cache

**Files:**
- Create: `services/domain/app/services/subject_resolver.rb`
- Test: `services/domain/test/services/subject_resolver_test.rb` (NEW)

- [ ] **Step 1: Write the failing test**

```ruby
# services/domain/test/services/subject_resolver_test.rb
require "test_helper"

class SubjectResolverTest < ActiveSupport::TestCase
  test "resolves real attributes from an existing Property" do
    Property.create!(address: "1 Oak St", state: "listed", region: "Austin 78704",
                     list_price: 500_000, sqft: 2000, beds: 4, baths: 2.5,
                     year_built: 1998, lat: 30.24, lng: -97.77,
                     source_name: "RentCast (live listing data)", captured_at: Time.current)

    s = SubjectResolver.new(address: "1 oak st").call

    assert s.present?
    assert_equal "Austin 78704", s.region
    assert_equal 2000, s.sqft
    assert_equal 4.0, s.beds
    assert_in_delta 30.24, s.latitude, 0.001
  end

  test "returns nil when the address is not in cache" do
    assert_nil SubjectResolver.new(address: "999 Unknown Rd").call
  end
end
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/domain && bin/rails test test/services/subject_resolver_test.rb`
Expected: FAIL with `uninitialized constant SubjectResolver`

- [ ] **Step 3: Implement**

```ruby
# services/domain/app/services/subject_resolver.rb
# Resolves a subject address to its REAL attributes from cache so the AVM values
# a real home, not an address hash. Order: an existing Property listing, then the
# PropertyRecordCache (Part D), else nil (caller falls back to the honest hash
# path + lower confidence). Reads only the DB.
class SubjectResolver
  Subject = Struct.new(:address, :region, :beds, :baths, :sqft, :lot_sqft,
                       :year_built, :latitude, :longitude, :garage_spaces,
                       keyword_init: true)

  def initialize(address:)
    @address = address.to_s.strip
  end

  def call
    from_property || from_record_cache
  end

  private

  def from_property
    p = Property.where("lower(address) = ?", @address.downcase).order(retired_at: :asc).first
    return nil unless p&.sqft.present?

    Subject.new(
      address: p.address, region: p.region, beds: p.beds.to_f, baths: p.baths.to_f,
      sqft: p.sqft.to_i, lot_sqft: nil, year_built: p.year_built,
      latitude: p.lat&.to_f, longitude: p.lng&.to_f, garage_spaces: nil,
    )
  end

  # Filled in Part D once PropertyRecordCache exists; nil-safe until then.
  def from_record_cache
    return nil unless defined?(PropertyRecordCache)
    rec = PropertyRecordCache.find_by("lower(address) = ?", @address.downcase)
    return nil unless rec&.sqft.present?

    Subject.new(
      address: rec.address, region: rec.region, beds: rec.beds.to_f, baths: rec.baths.to_f,
      sqft: rec.sqft.to_i, lot_sqft: rec.lot_sqft, year_built: rec.year_built,
      latitude: rec.lat&.to_f, longitude: rec.lng&.to_f, garage_spaces: rec.garage_spaces,
    )
  end
end
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/domain && bin/rails test test/services/subject_resolver_test.rb`
Expected: PASS (2 runs, 0 failures)

- [ ] **Step 5: Commit**

```bash
git add services/domain/app/services/subject_resolver.rb services/domain/test/services/subject_resolver_test.rb
git commit -m "feat(domain): SubjectResolver resolves real subject attributes from cache"
```

---

# PART C — Rails: assemble + wire into seller & buyer paths

### Task C1: extend `BrainValuationClient` to send features + comps + recency

**Files:**
- Modify: `services/domain/app/services/brain_valuation_client.rb`
- Test: `services/domain/test/services/brain_valuation_client_test.rb` (append)

- [ ] **Step 1: Write the failing test (append)**

```ruby
test "sends features + comps and maps freshness fields back" do
  captured = nil
  fake_stub = Object.new
  fake_stub.define_singleton_method(:get_valuation) do |req|
    captured = req
    Realestate::V1::GetValuationResponse.new(
      sufficient_data: true, estimate: 480_000, low: 440_000, high: 520_000,
      as_of: "2026-06-05T00:00:00Z", recent_activity: "3 new in 30d",
      facts: [Realestate::V1::SourceFact.new(source_id: "comp:1", kind: "comp:active_listing",
                                             description: "Active listing 2 Oak", contribution: 0)]
    )
  end

  comp = CompsSelector::Comp.new(id: "1", address: "2 Oak", price: 500_000, sqft: 2000,
                                 beds: 4, baths: 2, distance_mi: 0.3, age_days: 5)
  result = BrainValuationClient.new(stub: fake_stub).valuation(
    address: "1 Oak St",
    features: { beds: 4, baths: 2.5, sqft: 2000, year_built: 1998, latitude: 30.24, longitude: -97.77 },
    comps: [comp],
    as_of: "2026-06-05T00:00:00Z",
    recent_activity: "3 new in 30d",
  )

  assert_equal 4, captured.features.beds
  assert_equal 1, captured.comps.size
  assert_equal 500_000, captured.comps.first.price
  assert result.usable?
  assert_equal "2026-06-05T00:00:00Z", result.as_of
  assert_equal "3 new in 30d", result.recent_activity
end

test "address-only call still works (no features)" do
  fake_stub = Object.new
  fake_stub.define_singleton_method(:get_valuation) do |req|
    Realestate::V1::GetValuationResponse.new(sufficient_data: true, estimate: 500_000)
  end
  result = BrainValuationClient.new(stub: fake_stub).valuation(address: "5 Elm")
  assert result.usable?
  assert_nil result.as_of
end
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/domain && bin/rails test test/services/brain_valuation_client_test.rb`
Expected: FAIL (`valuation` doesn't accept `features:`; `Result` has no `as_of`).

- [ ] **Step 3: Implement**

Replace `services/domain/app/services/brain_valuation_client.rb` `Result` struct and `valuation` method:

```ruby
  Result = Struct.new(:sufficient_data, :estimate, :low, :high, :facts,
                      :as_of, :recent_activity, :error, keyword_init: true) do
    def ok? = error.nil?
    def usable? = ok? && sufficient_data && estimate.to_f.positive?
  end

  def valuation(address:, features: nil, comps: nil, as_of: nil, recent_activity: nil)
    req = Realestate::V1::GetValuationRequest.new(
      address: address.to_s,
      as_of: as_of.to_s,
      recent_activity: recent_activity.to_s,
    )
    req.features = build_features(features) if features.present?
    Array(comps).each { |c| req.comps << build_comp(c) }

    resp = stub.get_valuation(req)
    Result.new(
      sufficient_data: resp.sufficient_data,
      estimate: resp.estimate, low: resp.low, high: resp.high,
      facts: resp.facts.map { |f| Fact.new(source_id: f.source_id, kind: f.kind, description: f.description, contribution: f.contribution) },
      as_of: resp.as_of.presence,
      recent_activity: resp.recent_activity.presence,
      error: nil,
    )
  rescue StandardError => e
    Rails.logger.warn("[brain] valuation failed: #{e.class}: #{e.message}")
    Result.new(sufficient_data: false, estimate: 0, facts: [], error: "valuation_unavailable")
  end

  private

  def build_features(f)
    Realestate::V1::PropertyFeatures.new(
      beds: f[:beds].to_f, baths: f[:baths].to_f, sqft: f[:sqft].to_f,
      lot_sqft: f[:lot_sqft].to_f, year_built: f[:year_built].to_i,
      latitude: f[:latitude].to_f, longitude: f[:longitude].to_f,
      garage_spaces: f[:garage_spaces].to_f,
      condition: f[:condition].to_f, has_condition: !f[:condition].nil?,
    )
  end

  def build_comp(c)
    Realestate::V1::CompInput.new(
      id: c.id.to_s, price: c.price.to_f, sqft: c.sqft.to_f, beds: c.beds.to_f,
      baths: c.baths.to_f, distance_mi: c.distance_mi.to_f,
      age_days: c.age_days.to_i, address: c.address.to_s,
    )
  end
```

(The `private` keyword already precedes `stub`; place these helpers under the same `private` section.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/domain && bin/rails test test/services/brain_valuation_client_test.rb`
Expected: PASS (existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add services/domain/app/services/brain_valuation_client.rb services/domain/test/services/brain_valuation_client_test.rb
git commit -m "feat(domain): BrainValuationClient sends features/comps, maps freshness"
```

---

### Task C2: `ValuationAssembly` — one entry point used by seller + buyer

**Files:**
- Create: `services/domain/app/services/valuation_assembly.rb`
- Test: `services/domain/test/services/valuation_assembly_test.rb` (NEW)

- [ ] **Step 1: Write the failing test**

```ruby
# services/domain/test/services/valuation_assembly_test.rb
require "test_helper"

class ValuationAssemblyTest < ActiveSupport::TestCase
  def seed_pool
    Property.create!(address: "1 Oak St", state: "listed", region: "Austin 78704",
                     list_price: 500_000, sqft: 2000, beds: 4, baths: 2.5, year_built: 1998,
                     lat: 30.24, lng: -97.77, source_name: "RentCast (live listing data)",
                     captured_at: Time.current)
    Property.create!(address: "2 Oak St", state: "listed", region: "Austin 78704",
                     list_price: 520_000, sqft: 2050, beds: 4, baths: 2,
                     source_name: "RentCast (live listing data)", captured_at: Time.current)
    MarketSnapshot.create!(zip: "78704", area: "Austin 78704", median_price: 600_000,
                           new_listings: 3, avg_days_on_market: 21, as_of: Date.new(2026, 6, 5))
  end

  test "known address: sends real features + comps + recency to the brain" do
    seed_pool
    captured = nil
    fake = ->(**) { } # placeholder; replaced below
    client = Object.new
    client.define_singleton_method(:valuation) do |address:, features: nil, comps: nil, as_of: nil, recent_activity: nil|
      captured = { address:, features:, comps:, as_of:, recent_activity: }
      BrainValuationClient::Result.new(sufficient_data: true, estimate: 480_000,
        low: 440_000, high: 520_000, facts: [], as_of: as_of, recent_activity: recent_activity)
    end

    result = ValuationAssembly.new(address: "1 Oak St", client: client).call

    assert result.usable?
    assert_equal 2000, captured[:features][:sqft]                 # real subject sqft
    assert_equal ["2 Oak St"], captured[:comps].map(&:address)    # comp pool, subject excluded
    assert_match(/3 new listing/, captured[:recent_activity])     # honest recency
  end

  test "unknown address: falls back to address-only (no features), still ok" do
    captured = nil
    client = Object.new
    client.define_singleton_method(:valuation) do |address:, features: nil, **kw|
      captured = { features: features }
      BrainValuationClient::Result.new(sufficient_data: true, estimate: 500_000, facts: [])
    end

    result = ValuationAssembly.new(address: "999 Unknown Rd", client: client).call

    assert result.usable?
    assert_nil captured[:features] # honest: no real data => hash fallback, lower confidence
    assert result.low_confidence?
  end
end
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/domain && bin/rails test test/services/valuation_assembly_test.rb`
Expected: FAIL with `uninitialized constant ValuationAssembly`

- [ ] **Step 3: Implement**

```ruby
# services/domain/app/services/valuation_assembly.rb
# The single place that assembles a data-grounded valuation: resolve the
# subject's REAL attributes, pull comps from the cached pool, compute honest
# recency, and call the brain. Used by both the seller workspace and the buyer
# agent sidebar. Reads only the DB (zero RentCast). When the subject isn't in
# cache it falls back to the address-only path and flags low confidence rather
# than fabricating attributes.
class ValuationAssembly
  COMP_LIMIT = 6

  # Decorates the brain Result with a low-confidence flag for the fallback path.
  Result = SimpleDelegator
  def self.low_conf(result, flag)
    result.define_singleton_method(:low_confidence?) { flag }
    result
  end

  def initialize(address:, client: BrainValuationClient.new)
    @address = address.to_s.strip
    @client = client
  end

  def call
    subject = SubjectResolver.new(address: @address).call
    return value_unknown if subject.nil?

    activity = MarketActivity.new(region: subject.region).call
    comps = CompsSelector.new(region: subject.region, exclude_address: subject.address,
                              subject_sqft: subject.sqft).call(limit: COMP_LIMIT)

    result = @client.valuation(
      address: subject.address,
      features: {
        beds: subject.beds, baths: subject.baths, sqft: subject.sqft,
        lot_sqft: subject.lot_sqft, year_built: subject.year_built,
        latitude: subject.latitude, longitude: subject.longitude,
        garage_spaces: subject.garage_spaces,
      },
      comps: comps,
      as_of: activity.as_of&.to_s,
      recent_activity: activity.summary,
    )
    self.class.low_conf(result, false)
  end

  private

  def value_unknown
    result = @client.valuation(address: @address)
    self.class.low_conf(result, true)
  end
end
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/domain && bin/rails test test/services/valuation_assembly_test.rb`
Expected: PASS (2 runs, 0 failures)

- [ ] **Step 5: Commit**

```bash
git add services/domain/app/services/valuation_assembly.rb services/domain/test/services/valuation_assembly_test.rb
git commit -m "feat(domain): ValuationAssembly grounds valuation in real subject+comps+recency"
```

---

### Task C3: route the seller workspace through `ValuationAssembly`

**Files:**
- Modify: `services/domain/app/controllers/seller/valuations_controller.rb`
- Test: `services/domain/test/controllers/seller/valuations_controller_test.rb` (inspect existing; append)

- [ ] **Step 1: Write the failing test (append)**

First read the existing controller test to reuse its `valuation_client_override` seam, then append:

```ruby
test "seller valuation surfaces freshness from the assembled valuation" do
  Property.create!(address: "1 Oak St", state: "listed", region: "Austin 78704",
                   list_price: 500_000, sqft: 2000, beds: 4, baths: 2.5, year_built: 1998,
                   source_name: "RentCast (live listing data)", captured_at: Time.current)
  MarketSnapshot.create!(zip: "78704", area: "Austin 78704", median_price: 600_000,
                         new_listings: 3, avg_days_on_market: 21, as_of: Date.new(2026, 6, 5))
  sign_in_visitor # existing helper in this test file

  post seller_valuations_path, params: { address: "1 Oak St" }

  assert_response :success
  assert_match(/new listing/i, response.body)   # recent-activity surfaced
  assert_match(/as of/i, response.body)         # freshness label surfaced
end
```

> If the existing test file uses `valuation_client_override` to inject a fake brain, keep that override for the other tests but let THIS test run against the real `ValuationAssembly` with a stubbed `BrainValuationClient` (inject via the override returning a client whose `valuation` echoes freshness). Match the file's established pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/domain && bin/rails test test/controllers/seller/valuations_controller_test.rb`
Expected: FAIL (freshness text not in the view yet).

- [ ] **Step 3: Implement the controller change**

In `services/domain/app/controllers/seller/valuations_controller.rb`, replace the valuation call:

```ruby
      @valuation = ValuationAssembly.new(address: @address, client: valuation_client).call
```

Keep `valuation_client` (the test seam) returning a `BrainValuationClient` by default. `@valuation` still responds to `usable?` / `ok?` / `estimate` (via `SimpleDelegator`) plus `as_of` / `recent_activity` / `low_confidence?`.

- [ ] **Step 4: Update the view (Task C5 covers the markup) then re-run**

Run: `cd services/domain && bin/rails test test/controllers/seller/valuations_controller_test.rb`
Expected: PASS after C5's view edit; if running C3 before C5, this stays red until C5 — that's expected, commit C3+C5 together.

- [ ] **Step 5: Commit (with C5)**

Defer the commit to the end of C5 so the controller + view land together.

---

### Task C4: route the buyer agent sidebar price-check through `ValuationAssembly`

**Files:**
- Modify: `services/domain/app/controllers/agent/messages_controller.rb` (the valuation/price-check branch)
- Test: `services/domain/test/controllers/agent/messages_controller_test.rb` (append)

- [ ] **Step 1: Read the price-check branch**

Run: `grep -n "valuation\|price_check\|BrainValuationClient\|GetValuation" services/domain/app/controllers/agent/messages_controller.rb`
Identify where the sidebar produces a price check (the `_price_check` partial's data).

- [ ] **Step 2: Write the failing test (append)**

```ruby
test "agent sidebar price check is grounded in real comps + freshness" do
  Property.create!(address: "1 Oak St", state: "listed", region: "Austin 78704",
                   list_price: 500_000, sqft: 2000, beds: 4, baths: 2.5, year_built: 1998,
                   source_name: "RentCast (live listing data)", captured_at: Time.current)
  Property.create!(address: "2 Oak St", state: "listed", region: "Austin 78704",
                   list_price: 520_000, sqft: 2050, beds: 4, baths: 2,
                   source_name: "RentCast (live listing data)", captured_at: Time.current)
  MarketSnapshot.create!(zip: "78704", area: "Austin 78704", median_price: 600_000,
                         new_listings: 3, avg_days_on_market: 21, as_of: Date.new(2026, 6, 5))
  sign_in_visitor

  post agent_messages_path, params: price_check_params(address: "1 Oak St") # match existing helper

  assert_response :success
  assert_match(/Active listing/i, response.body) # comp citation surfaced
end
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd services/domain && bin/rails test test/controllers/agent/messages_controller_test.rb`
Expected: FAIL (no comp citation in the rendered price check).

- [ ] **Step 4: Implement**

In the price-check branch of `agent/messages_controller.rb`, replace the direct `BrainValuationClient.new.valuation(address:)` call with:

```ruby
        @valuation = ValuationAssembly.new(address: @address).call
```

Pass `@valuation` to the `_price_check` partial as it already is (the partial reads `estimate` / `low` / `high` / `facts`, now also `as_of` / `recent_activity`).

- [ ] **Step 5: Run test (passes after C5 view edit) + commit with C5.**

---

### Task C5: surface freshness + comps in both views

**Files:**
- Modify: `services/domain/app/views/seller/valuations/create.html.erb`
- Modify: `services/domain/app/views/agent/messages/_price_check.html.erb`

- [ ] **Step 1: Read both views** to match existing markup/classes (`mk-badge`, drivers list).

Run: `sed -n '1,80p' services/domain/app/views/agent/messages/_price_check.html.erb`

- [ ] **Step 2: Add a freshness + comps block to `_price_check.html.erb`**

After the estimate/drivers section, add (using the partial's local `valuation` / `@valuation`):

```erb
<% val = local_assigns.fetch(:valuation, @valuation) %>
<% if val.respond_to?(:as_of) && val.as_of.present? %>
  <p class="mk-meta">📅 Data as of <%= val.as_of.to_date.strftime("%b %-d, %Y") rescue val.as_of %> · updated ~daily</p>
<% end %>
<% if val.respond_to?(:recent_activity) && val.recent_activity.present? %>
  <p class="mk-meta">📈 <%= val.recent_activity %></p>
<% end %>
<% comp_facts = Array(val.facts).select { |f| f.kind == "comp:active_listing" } %>
<% if comp_facts.any? %>
  <details class="mk-comps">
    <summary>Comparable active listings used (<%= comp_facts.size %>)</summary>
    <ul>
      <% comp_facts.each do |f| %><li><%= f.description %></li><% end %>
    </ul>
  </details>
<% end %>
<% if val.respond_to?(:low_confidence?) && val.low_confidence? %>
  <p class="mk-meta mk-meta--warn">⚠ Limited data for this address — estimate shown at lower confidence.</p>
<% end %>
```

- [ ] **Step 3: Add the same block to `seller/valuations/create.html.erb`**

Insert the identical block (referencing `@valuation`) into the valuation result section of the seller view, matching its existing markup.

- [ ] **Step 4: Run the affected controller tests**

Run: `cd services/domain && bin/rails test test/controllers/seller/valuations_controller_test.rb test/controllers/agent/messages_controller_test.rb`
Expected: PASS (C3 + C4 + C5 together).

- [ ] **Step 5: Commit C3 + C4 + C5 together**

```bash
git add services/domain/app/controllers/seller/valuations_controller.rb \
        services/domain/app/controllers/agent/messages_controller.rb \
        services/domain/app/views/seller/valuations/create.html.erb \
        services/domain/app/views/agent/messages/_price_check.html.erb \
        services/domain/test/controllers/seller/valuations_controller_test.rb \
        services/domain/test/controllers/agent/messages_controller_test.rb
git commit -m "feat(domain): seller + buyer valuation grounded in comps, with freshness UI"
```

---

# PART D — Quota-bounded "any address" path (the only RentCast spend)

> Parts A–C already deliver real, comps-anchored, fresh valuations for every address in our imported pool (the listings users actually click). Part D extends coverage to an arbitrary typed address via a **capped, cache-first** RentCast property-record lookup, so each unique address costs at most one call ever, and the demo (pre-warmed) costs zero.

### Task D1: `PropertyRecordCache` model + migration

**Files:**
- Create: `services/domain/db/migrate/20260606000001_create_property_record_caches.rb`
- Modify: `services/domain/db/schema.rb` (hand-add the table — local Postgres isn't running; tests load schema.rb)
- Create: `services/domain/app/models/property_record_cache.rb`
- Test: `services/domain/test/models/property_record_cache_test.rb` (NEW)

- [ ] **Step 1: Write the migration**

```ruby
# services/domain/db/migrate/20260606000001_create_property_record_caches.rb
class CreatePropertyRecordCaches < ActiveRecord::Migration[8.1]
  def change
    create_table :property_record_caches do |t|
      t.string :address, null: false
      t.string :region
      t.integer :beds
      t.decimal :baths, precision: 3, scale: 1
      t.integer :sqft
      t.decimal :lot_sqft, precision: 12, scale: 1
      t.integer :year_built
      t.decimal :lat, precision: 10, scale: 6
      t.decimal :lng, precision: 10, scale: 6
      t.decimal :garage_spaces, precision: 4, scale: 1
      t.decimal :tax_assessed_value, precision: 12, scale: 2
      t.datetime :captured_at
      t.timestamps
    end
    add_index :property_record_caches, :address, unique: true
  end
end
```

- [ ] **Step 2: Hand-add the table to `db/schema.rb`** (bump the version line at top to `2026_06_06_000001` and add the matching `create_table "property_record_caches"` block mirroring the migration columns + the unique address index).

- [ ] **Step 3: Write the model + test**

```ruby
# services/domain/app/models/property_record_cache.rb
class PropertyRecordCache < ApplicationRecord
  validates :address, presence: true, uniqueness: { case_sensitive: false }

  # Stale after this TTL; the prewarm task refreshes only past-TTL rows.
  TTL = 14.days
  scope :fresh, -> { where("captured_at >= ?", TTL.ago) }
  def fresh? = captured_at.present? && captured_at >= TTL.ago
end
```

```ruby
# services/domain/test/models/property_record_cache_test.rb
require "test_helper"

class PropertyRecordCacheTest < ActiveSupport::TestCase
  test "fresh? reflects the TTL" do
    rec = PropertyRecordCache.new(address: "1 A", captured_at: 1.day.ago)
    assert rec.fresh?
    rec.captured_at = 30.days.ago
    refute rec.fresh?
  end

  test "address uniqueness is case-insensitive" do
    PropertyRecordCache.create!(address: "1 Oak St")
    dup = PropertyRecordCache.new(address: "1 oak st")
    refute dup.valid?
  end
end
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/domain && bin/rails test test/models/property_record_cache_test.rb`
Expected: PASS (schema.rb loads the new table; 2 runs, 0 failures)

- [ ] **Step 5: Commit**

```bash
git add services/domain/db/migrate/20260606000001_create_property_record_caches.rb \
        services/domain/db/schema.rb services/domain/app/models/property_record_cache.rb \
        services/domain/test/models/property_record_cache_test.rb
git commit -m "feat(domain): PropertyRecordCache for per-address real attributes"
```

---

### Task D2: `RentCastClient#property_record` (single-address lookup)

**Files:**
- Modify: `services/domain/app/services/rent_cast_client.rb`
- Test: `services/domain/test/services/rent_cast_client_test.rb` (NEW; or append if exists)

- [ ] **Step 1: Write the failing test**

```ruby
# services/domain/test/services/rent_cast_client_test.rb
require "test_helper"

class RentCastClientTest < ActiveSupport::TestCase
  test "property_record returns nil without an api key (no network)" do
    assert_nil RentCastClient.new(api_key: nil).property_record(address: "1 Oak St")
  end
end
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/domain && bin/rails test test/services/rent_cast_client_test.rb`
Expected: FAIL with `NoMethodError: undefined method 'property_record'`

- [ ] **Step 3: Implement**

Add to `services/domain/app/services/rent_cast_client.rb`:

```ruby
  # A single property's record (real attributes + tax assessment) for one
  # address. ONE request per address — callers MUST cache (PropertyRecordCache).
  # Returns the first matching record hash, or nil.
  def property_record(address:)
    body = get("/properties", address: address)
    rec = body.is_a?(Array) ? body.first : body
    rec.is_a?(Hash) ? rec : nil
  end
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/domain && bin/rails test test/services/rent_cast_client_test.rb`
Expected: PASS (1 run, 0 failures)

- [ ] **Step 5: Commit**

```bash
git add services/domain/app/services/rent_cast_client.rb services/domain/test/services/rent_cast_client_test.rb
git commit -m "feat(domain): RentCastClient#property_record single-address lookup"
```

---

### Task D3: capped, cache-first `rentcast:prewarm` task

**Files:**
- Modify: `services/domain/lib/tasks/rentcast.rake`
- Create: `services/domain/app/services/property_record_prewarm.rb`
- Test: `services/domain/test/services/property_record_prewarm_test.rb` (NEW)

- [ ] **Step 1: Write the failing test**

```ruby
# services/domain/test/services/property_record_prewarm_test.rb
require "test_helper"

class PropertyRecordPrewarmTest < ActiveSupport::TestCase
  class FakeClient
    attr_reader :calls
    def initialize(records) = (@records = records; @calls = 0)
    def configured? = true
    def property_record(address:)
      @calls += 1
      @records[address]
    end
  end

  test "caps the number of RentCast calls and is cache-first" do
    records = {
      "1 A St" => { "bedrooms" => 3, "bathrooms" => 2, "squareFootage" => 1500,
                    "yearBuilt" => 1990, "latitude" => 30.2, "longitude" => -97.7,
                    "taxAssessments" => { "2025" => { "value" => 410_000 } } },
      "2 B St" => { "bedrooms" => 4, "bathrooms" => 3, "squareFootage" => 2200 },
    }
    client = FakeClient.new(records)
    # Already-fresh cache row should be skipped.
    PropertyRecordCache.create!(address: "2 B St", sqft: 2200, captured_at: 1.hour.ago)

    result = PropertyRecordPrewarm.new(client: client).call(addresses: ["1 A St", "2 B St"], max_calls: 5)

    assert_equal 1, client.calls                    # only the missing one fetched
    assert PropertyRecordCache.find_by("lower(address)=?", "1 a st").sqft == 1500
    assert_equal 1, result.fetched
    assert_equal 1, result.skipped_fresh
  end

  test "refuses to exceed max_calls" do
    records = Hash.new { |h, k| h[k] = { "bedrooms" => 3, "bathrooms" => 2, "squareFootage" => 1500 } }
    client = FakeClient.new(records)
    addresses = (1..10).map { |i| "#{i} St" }

    result = PropertyRecordPrewarm.new(client: client).call(addresses: addresses, max_calls: 3)

    assert_equal 3, client.calls
    assert_equal 3, result.fetched
    assert_equal 7, result.skipped_budget
  end
end
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/domain && bin/rails test test/services/property_record_prewarm_test.rb`
Expected: FAIL with `uninitialized constant PropertyRecordPrewarm`

- [ ] **Step 3: Implement the service**

```ruby
# services/domain/app/services/property_record_prewarm.rb
# Pre-warms PropertyRecordCache from RentCast, off the request path. HARD-CAPPED
# by max_calls and CACHE-FIRST (skips rows still within TTL), so a refresh costs
# a bounded, logged number of RentCast requests — never per web request. This is
# the ONLY code that spends RentCast quota for valuation.
class PropertyRecordPrewarm
  Result = Struct.new(:fetched, :skipped_fresh, :skipped_budget, keyword_init: true)

  def initialize(client: RentCastClient.new)
    @client = client
  end

  def call(addresses:, max_calls: 25)
    fetched = skipped_fresh = skipped_budget = 0
    Array(addresses).each do |address|
      existing = PropertyRecordCache.find_by("lower(address) = ?", address.downcase)
      if existing&.fresh?
        skipped_fresh += 1
        next
      end
      if fetched >= max_calls
        skipped_budget += 1
        next
      end
      rec = @client.property_record(address: address)
      fetched += 1 # a call was spent even if the record is blank
      upsert(address, rec) if rec
    end
    Rails.logger.info("[prewarm] property records: fetched=#{fetched} (RentCast calls), " \
                      "skipped_fresh=#{skipped_fresh} skipped_budget=#{skipped_budget}")
    Result.new(fetched: fetched, skipped_fresh: skipped_fresh, skipped_budget: skipped_budget)
  end

  private

  def upsert(address, rec)
    cache = PropertyRecordCache.find_or_initialize_by(address: address)
    cache.assign_attributes(
      region: rec["zipCode"].present? ? "Austin #{rec["zipCode"]}" : cache.region,
      beds: rec["bedrooms"]&.to_i, baths: rec["bathrooms"], sqft: rec["squareFootage"]&.to_i,
      lot_sqft: rec["lotSize"], year_built: rec["yearBuilt"]&.to_i,
      lat: rec["latitude"], lng: rec["longitude"],
      tax_assessed_value: latest_assessment(rec),
      captured_at: Time.current,
    )
    cache.save!
  rescue ActiveRecord::RecordInvalid => e
    Rails.logger.warn("[prewarm] skipped #{address}: #{e.message}")
  end

  def latest_assessment(rec)
    assessments = rec["taxAssessments"]
    return nil unless assessments.is_a?(Hash) && assessments.any?
    year = assessments.keys.max
    assessments.dig(year, "value")
  end
end
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/domain && bin/rails test test/services/property_record_prewarm_test.rb`
Expected: PASS (2 runs, 0 failures)

- [ ] **Step 5: Add the rake task**

Append to `services/domain/lib/tasks/rentcast.rake` (inside `namespace :rentcast`):

```ruby
  desc "Pre-warm PropertyRecordCache for a bounded address set (caps RentCast calls). " \
       "ADDRESSES='a;b;c' MAX_CALLS=25"
  task prewarm: :environment do
    client = RentCastClient.new
    unless client.configured?
      warn "RENTCAST_API_KEY not set — skipping prewarm."
      next
    end
    addresses = ENV["ADDRESSES"].to_s.split(";").map(&:strip).reject(&:empty?)
    if addresses.empty?
      # Default: warm the browsable listing addresses missing a fresh record.
      addresses = Property.browsable.where(region: RentCastImport::DEFAULT_MARKET_ZIPS.map { |z| "Austin #{z}" })
                          .limit((ENV["MAX_CALLS"] || 25).to_i).pluck(:address)
    end
    result = PropertyRecordPrewarm.new(client: client)
                                  .call(addresses: addresses, max_calls: (ENV["MAX_CALLS"] || 25).to_i)
    puts "Prewarm: fetched #{result.fetched} (RentCast calls), " \
         "skipped #{result.skipped_fresh} fresh / #{result.skipped_budget} over-budget."
  end
```

- [ ] **Step 6: Commit**

```bash
git add services/domain/app/services/property_record_prewarm.rb \
        services/domain/lib/tasks/rentcast.rake \
        services/domain/test/services/property_record_prewarm_test.rb
git commit -m "feat(domain): capped cache-first property-record prewarm task"
```

---

# PART E — Integration, docs, verification

### Task E1: full suites green

- [ ] **Step 1: Brain suite**

Run: `cd services/brain && python3 -m pytest -q`
Expected: all pass.

- [ ] **Step 2: Rails suite**

Run: `cd services/domain && bin/rails test`
Expected: all pass (was 196; new tests added).

- [ ] **Step 3: Cross-language smoke (optional, needs local ports free)**

Run: `make smoke`
Expected: gateway → brain round-trip returns a valuation (address-only path unaffected).

- [ ] **Step 4: Commit any fixups**

```bash
git commit -am "test: green brain + rails suites for real-time valuation" --allow-empty
```

---

### Task E2: docs

**Files:**
- Modify: `README.md` (R3 row in the capability matrix), `docs/ARCHITECTURE.md` (§13 valuation seam row), `services/domain/README.md` (prewarm task + config), `deploy/fly/DEPLOY.md` (prewarm note).

- [ ] **Step 1: README** — update the R3 / "Predictive Pricing" capability line from "real model, synthetic features, static" to: real model **grounded in real comps + per-ZIP market freshness**, value any browsable address, honest "as of" + recent-activity, citations per comp; arbitrary-address coverage via a capped cache-first prewarm; live site never calls RentCast.

- [ ] **Step 2: ARCHITECTURE §13** — change the Valuation/Listings rows to note the comp-anchored, freshness-aware path and the `PropertyRecordCache` + capped prewarm seam.

- [ ] **Step 3: domain/README** — document `rake rentcast:prewarm ADDRESSES=… MAX_CALLS=…` and that valuation reads cache only.

- [ ] **Step 4: DEPLOY** — note the optional one-time `rentcast:prewarm` after an import, and that the request path/demo spends zero RentCast.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/ARCHITECTURE.md services/domain/README.md deploy/fly/DEPLOY.md
git commit -m "docs: real-time valuation (comps-anchored, freshness, capped prewarm)"
```

---

### Task E3: merge to main

- [ ] **Step 1: Re-run both suites once more** (E1 commands). Expected: green.
- [ ] **Step 2: Fast-forward merge** the worktree branch into `main` (do NOT push unless the user asks):

```bash
git -C "/Users/rikki/Desktop/AI Real Estate Agent" merge --ff-only feat/brain-realtime-pillars
```

- [ ] **Step 3: Report** the new test counts and confirm the live site/demo still serves valuations from cache with zero RentCast calls.

---

## Self-Review notes (verify during execution)

- **Spec coverage:** comps-anchor (A3/A4), real features (A1/A6), honest freshness/as_of (B2, A2, C5), cache-first + capped quota (D3), zero-call request path (B1–C2 read DB only), low-confidence fallback for uncovered addresses (C2/C5), citations per comp (A3/C5). All spec sections map to a task.
- **Type consistency:** `CompInput` fields (id, price, sqft, beds, baths, distance_mi, age_days, address) are identical across proto (A5), Python schema (A2), `CompsSelector::Comp` (B1), and `BrainValuationClient#build_comp` (C1). `Valuation.as_of/recent_activity` consistent across A2/A4/A6/C1. `ValuationAssembly` result exposes `usable?`/`estimate`/`as_of`/`recent_activity`/`low_confidence?` consumed by C3/C4/C5.
- **Quota:** only D2/D3 touch RentCast; both are capped + cache-first and off the request path.
