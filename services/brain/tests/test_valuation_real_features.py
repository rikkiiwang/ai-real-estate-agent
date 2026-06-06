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
