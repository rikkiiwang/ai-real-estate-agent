"""VisionServicer.AnalyzePhotos tests (no network, no API key).

Monkeypatch the photo fetch + the model factory so the servicer runs against
canned findings deterministically.
"""
from __future__ import annotations

from genproto.realestate.v1 import realestate_pb2 as pb

from brain import server
from brain.vision import FakeVisionModel


def _patch(monkeypatch, canned, *, fetch=b"img"):
    monkeypatch.setattr(server, "_fetch_image", lambda url, **kw: fetch)
    monkeypatch.setattr(server, "claude_vision_model_or_none", lambda **kw: FakeVisionModel(canned=canned))


def test_analyze_photos_returns_findings_condition_and_provenance(monkeypatch):
    _patch(monkeypatch, {
        "u1": [
            {"kind": "feature", "label": "updated_kitchen", "confidence": 0.9},
            {"kind": "red_flag", "label": "water_stain", "confidence": 0.8},
        ]
    })
    resp = server.VisionServicer().AnalyzePhotos(
        pb.AnalyzePhotosRequest(address="1 Oak St", photo_urls=["u1"]), None
    )

    assert [f.label for f in resp.findings] == ["updated_kitchen"]      # buyer-safe feature
    assert [f.label for f in resp.needs_review] == ["water_stain"]      # red-flag → review
    assert resp.findings[0].evidence_photo_id == "u1"                   # cited to the photo
    assert resp.provenance == "fake"                                    # no real key in tests
    assert 0.0 <= resp.condition <= 1.0
    assert resp.condition < 0.5  # a red-flag pulls condition below neutral


def test_unfetchable_photo_is_skipped_not_fatal(monkeypatch):
    _patch(monkeypatch, {}, fetch=None)  # every fetch fails
    resp = server.VisionServicer().AnalyzePhotos(
        pb.AnalyzePhotosRequest(address="x", photo_urls=["bad1", "bad2"]), None
    )
    assert list(resp.findings) == []
    assert resp.condition == 0.5  # neutral when nothing analyzed
    assert resp.provenance == "fake"
