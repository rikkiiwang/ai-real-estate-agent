"""Feature derivation for the AVM.

Two responsibilities, kept deterministic and hermetic:

* Turn an address into a normalized :class:`PropertyRecord`. The real ingestion
  join (TCAD + GIS + listings) lands in U2/U5; here the record is derived
  deterministically from the address string so the AVM is stable and testable
  without external data or network. Blank / explicitly-uncovered addresses have
  no record (``None``) — the engine returns insufficient_data for those.
* Turn a :class:`PropertyRecord` into a fixed-order feature vector, with stable
  human-readable feature names so contributions can be cited as source facts.

The feature order here is the single source of truth shared by the synthetic
training-data generator and the model, so training and inference never disagree.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from .schema import PropertyRecord

# Reference year for deriving property age; fixed so the AVM is time-stable.
REFERENCE_YEAR: int = 2026

# Austin, TX bounding box (approx) for synthetic geo features.
_LAT_MIN, _LAT_MAX = 30.10, 30.52
_LON_MIN, _LON_MAX = -97.94, -97.56
# A central reference point (roughly downtown Austin) for a distance feature.
_LAT_CENTER, _LON_CENTER = 30.2672, -97.7431

# Fixed feature order. Names are stable tokens used in citations.
FEATURE_NAMES: tuple[str, ...] = (
    "beds",
    "baths",
    "sqft",
    "lot_sqft",
    "age",
    "garage_spaces",
    "dist_to_center_km",
    "condition",
)

# A small set of addresses deliberately marked as having no ingested coverage,
# so the insufficient-data path is exercisable. Matched case-insensitively on a
# normalized form. Real coverage is a data-join question (U2/U5).
_UNCOVERED_MARKERS: frozenset[str] = frozenset({"unknown", "no coverage", "nowhere"})

# Default condition used when no photo-derived signal is supplied. 0.5 = neutral.
_DEFAULT_CONDITION: float = 0.5


def _normalize(address: str) -> str:
    return " ".join((address or "").split()).strip().lower()


def _seed(address: str) -> int:
    """Stable 64-bit seed from the normalized address (hash-randomization safe)."""
    digest = hashlib.sha256(_normalize(address).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _unit(seed: int, salt: int) -> float:
    """A deterministic pseudo-uniform value in ``[0, 1)`` from ``seed`` + ``salt``."""
    h = hashlib.sha256(f"{seed}:{salt}".encode("ascii")).digest()
    return int.from_bytes(h[:8], "big") / 2**64


def is_covered(address: str) -> bool:
    """True when ``address`` has ingested coverage (so a valuation is honest).

    Blank addresses and a small explicit uncovered set return ``False``; the
    engine maps that to ``sufficient_data=False`` rather than guessing a number.
    """
    norm = _normalize(address)
    if not norm:
        return False
    return not any(marker in norm for marker in _UNCOVERED_MARKERS)


def derive_record(
    address: str,
    *,
    condition: Optional[float] = None,
) -> Optional[PropertyRecord]:
    """Derive a deterministic :class:`PropertyRecord` for ``address``.

    Returns ``None`` when the address has no coverage. ``condition`` (if given)
    is the photo-derived condition score in ``[0, 1]`` from U4's vision output;
    it is injected here, never imported, keeping the AVM independent of vision.
    """
    if not is_covered(address):
        return None

    seed = _seed(address)

    # Realistic-ish, correlated synthetic attributes. Deterministic per address.
    beds = 2 + int(_unit(seed, 1) * 4)  # 2..5
    baths = 1.0 + round(_unit(seed, 2) * 3.0 * 2) / 2  # 1.0..4.0 in 0.5 steps
    sqft = 900.0 + _unit(seed, 3) * 3100.0 + (beds - 2) * 250.0  # ~900..4250
    lot_sqft = 3000.0 + _unit(seed, 4) * 9000.0
    year_built = 1945 + int(_unit(seed, 5) * (REFERENCE_YEAR - 1945 - 1))
    garage_spaces = float(int(_unit(seed, 6) * 3))  # 0..2
    latitude = _LAT_MIN + _unit(seed, 7) * (_LAT_MAX - _LAT_MIN)
    longitude = _LON_MIN + _unit(seed, 8) * (_LON_MAX - _LON_MIN)

    if condition is not None:
        condition = max(0.0, min(1.0, float(condition)))

    return PropertyRecord(
        address=address.strip(),
        beds=float(beds),
        baths=float(baths),
        sqft=float(sqft),
        lot_sqft=float(lot_sqft),
        year_built=year_built,
        latitude=latitude,
        longitude=longitude,
        garage_spaces=garage_spaces,
        condition=condition,
        source_ids=(
            f"tcad:parcel:{seed % 1_000_000:06d}",
            f"gis:geo:{seed % 997:03d}",
        ),
    )


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
        lot_sqft=float(lot_sqft) if lot_sqft is not None else _DEFAULT_LOT_SQFT,
        year_built=int(year_built) if year_built is not None else _DEFAULT_YEAR_BUILT,
        latitude=float(latitude) if latitude is not None else _LAT_CENTER,
        longitude=float(longitude) if longitude is not None else _LON_CENTER,
        garage_spaces=float(garage_spaces) if garage_spaces is not None else 0.0,
        condition=condition,
        source_ids=("listing:rentcast",),
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km. Pure-Python (no numpy needed for one call)."""
    import math

    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def feature_vector(record: PropertyRecord) -> list[float]:
    """Project a :class:`PropertyRecord` onto the fixed-order feature vector.

    A missing photo-condition signal falls back to a neutral default so the
    record is still valued (sparsity is handled by widening the band upstream,
    not by inventing a confident condition).
    """
    age = float(max(0, REFERENCE_YEAR - record.year_built))
    dist = _haversine_km(record.latitude, record.longitude, _LAT_CENTER, _LON_CENTER)
    condition = _DEFAULT_CONDITION if record.condition is None else record.condition
    return [
        record.beds,
        record.baths,
        record.sqft,
        record.lot_sqft,
        age,
        record.garage_spaces,
        dist,
        condition,
    ]
