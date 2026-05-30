"""U4 verification: photo analysis emits schema-valid, routed findings only.

All tests use FakeVisionModel — no network, no API key. They cover the four U4
scenarios: clear feature -> feature w/ photo reference; ambiguous image -> low
confidence (not a confident claim); corrupt/missing image -> graceful handling;
visible defect -> red_flag routed to review.
"""
import pytest

from brain.vision import (
    BBox,
    DEFAULT_REDFLAG_CONFIDENCE,
    FakeVisionModel,
    Finding,
    GeminiVisionModel,
    PhotoAnalyzer,
    PhotoRef,
)
from brain.vision.model import FINDINGS_FUNCTION_SCHEMA


# --- schema validation -------------------------------------------------------

def test_finding_rejects_bad_kind():
    with pytest.raises(ValueError):
        Finding(kind="prose", label="x", confidence=0.5, evidence_photo_id="p1")


def test_finding_rejects_out_of_range_confidence():
    with pytest.raises(ValueError):
        Finding(kind="feature", label="x", confidence=1.5, evidence_photo_id="p1")


def test_finding_requires_photo_citation():
    with pytest.raises(ValueError):
        Finding(kind="feature", label="x", confidence=0.9, evidence_photo_id="")


def test_bbox_rejects_out_of_bounds():
    with pytest.raises(ValueError):
        BBox(x=0.8, y=0.0, width=0.5, height=0.1)  # x+width > 1


# --- happy path: a clear feature yields that feature with a photo reference ---

def test_clear_feature_yields_feature_with_photo_reference():
    model = FakeVisionModel(
        canned={
            "kitchen-01": [
                {
                    "kind": "feature",
                    "label": "granite_countertops",
                    "confidence": 0.95,
                    "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.2},
                }
            ]
        }
    )
    analyzer = PhotoAnalyzer(model)
    ref = PhotoRef(photo_id="kitchen-01", uri="fixtures/kitchen-01.jpg")

    result = analyzer.analyze([(ref, b"\xff\xd8fakejpegbytes")])

    assert len(result.features) == 1
    feature = result.features[0]
    assert feature.kind == "feature"
    assert feature.label == "granite_countertops"
    assert feature.evidence_photo_id == "kitchen-01"  # cited to the source photo
    assert feature.bbox is not None
    assert not result.needs_review
    assert not result.errors


# --- edge: ambiguous image -> low confidence, not a confident claim ----------

def test_ambiguous_image_is_low_confidence_not_a_confident_claim():
    model = FakeVisionModel(
        canned={
            "blurry-02": [
                {
                    "kind": "feature",
                    "label": "hardwood_floors",
                    "confidence": 0.3,  # below threshold
                }
            ]
        }
    )
    analyzer = PhotoAnalyzer(model)
    ref = PhotoRef(photo_id="blurry-02")

    result = analyzer.analyze([(ref, b"img")])

    # Not asserted downstream as a feature; routed to review instead.
    assert result.features == []
    assert len(result.needs_review) == 1
    assert result.needs_review[0].confidence < DEFAULT_REDFLAG_CONFIDENCE


# --- error: corrupt/missing image handled gracefully -------------------------

def test_missing_image_handled_gracefully():
    model = FakeVisionModel(canned={"x": [{"kind": "feature", "label": "f", "confidence": 0.9}]})
    analyzer = PhotoAnalyzer(model)

    result = analyzer.analyze(
        [
            (PhotoRef(photo_id="missing"), None),
            (PhotoRef(photo_id="empty"), b""),
        ]
    )

    assert result.features == []
    assert result.needs_review == []
    assert {e.photo_id for e in result.errors} == {"missing", "empty"}
    # FakeVisionModel was never called for missing images.
    assert model.calls == []


def test_model_failure_is_isolated_per_photo():
    class BoomModel:
        def analyze_photo(self, image_bytes, ref):
            if ref.photo_id == "boom":
                raise RuntimeError("decode failed")
            return [{"kind": "feature", "label": "ok_feature", "confidence": 0.9}]

    analyzer = PhotoAnalyzer(BoomModel())
    result = analyzer.analyze(
        [
            (PhotoRef(photo_id="boom"), b"corrupt"),
            (PhotoRef(photo_id="good"), b"img"),
        ]
    )

    assert [f.label for f in result.features] == ["ok_feature"]  # batch survived
    assert len(result.errors) == 1
    assert result.errors[0].photo_id == "boom"


def test_malformed_finding_recorded_as_error_not_crash():
    model = FakeVisionModel(
        canned={"p": [{"kind": "feature", "label": "good", "confidence": 0.9},
                      {"label": "no_kind", "confidence": 0.9}]}  # missing 'kind'
    )
    analyzer = PhotoAnalyzer(model)
    result = analyzer.analyze([(PhotoRef(photo_id="p"), b"img")])

    assert [f.label for f in result.features] == ["good"]
    assert len(result.errors) == 1


# --- red-flag: visible defect emits a red_flag routed to review --------------

def test_visible_defect_emits_red_flag_routed_to_review():
    model = FakeVisionModel(
        canned={
            "ceiling-03": [
                {
                    "kind": "red_flag",
                    "label": "water_stain_ceiling",
                    "confidence": 0.92,  # high confidence still routes to review
                }
            ]
        }
    )
    analyzer = PhotoAnalyzer(model)
    ref = PhotoRef(photo_id="ceiling-03")

    result = analyzer.analyze([(ref, b"img")])

    assert result.features == []  # red-flags are never asserted as features
    assert len(result.needs_review) == 1
    rf = result.needs_review[0]
    assert rf.is_red_flag
    assert rf.label == "water_stain_ceiling"
    assert rf.evidence_photo_id == "ceiling-03"


def test_mixed_batch_routes_features_and_redflags_separately():
    model = FakeVisionModel(
        canned={
            "p1": [{"kind": "feature", "label": "granite_countertops", "confidence": 0.9}],
            "p2": [{"kind": "red_flag", "label": "foundation_crack", "confidence": 0.8}],
            "p3": [{"kind": "feature", "label": "maybe_pool", "confidence": 0.2}],
        }
    )
    analyzer = PhotoAnalyzer(model)
    result = analyzer.analyze(
        [
            (PhotoRef(photo_id="p1"), b"a"),
            (PhotoRef(photo_id="p2"), b"b"),
            (PhotoRef(photo_id="p3"), b"c"),
        ]
    )

    assert [f.label for f in result.features] == ["granite_countertops"]
    review_labels = {f.label for f in result.needs_review}
    assert review_labels == {"foundation_crack", "maybe_pool"}
    assert len(result.all_findings) == 3


# --- GeminiVisionModel: builds a structured request, never needs a network ----

def test_gemini_builds_structured_output_request_without_sending():
    model = GeminiVisionModel()  # no client injected
    req = model.build_request(b"\xff\xd8jpeg", PhotoRef(photo_id="abc"))

    assert req["tools"][0]["function_declarations"][0] is FINDINGS_FUNCTION_SCHEMA
    assert req["tool_config"]["function_calling_config"]["mode"] == "ANY"
    assert req["photo_id"] == "abc"


def test_gemini_without_client_refuses_to_run():
    model = GeminiVisionModel()
    with pytest.raises(RuntimeError):
        model.analyze_photo(b"img", PhotoRef(photo_id="abc"))
