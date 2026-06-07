"""condition_from_findings tests (pure, deterministic)."""
from __future__ import annotations

from brain.vision import condition_from_findings
from brain.vision.schema import Finding


def feature(label, conf):
    return Finding(kind="feature", label=label, confidence=conf, evidence_photo_id="p1")


def red_flag(label, conf):
    return Finding(kind="red_flag", label=label, confidence=conf, evidence_photo_id="p1")


def test_no_findings_is_neutral():
    assert condition_from_findings([], []) == 0.5


def test_features_raise_condition():
    score = condition_from_findings([feature("updated_kitchen", 1.0), feature("hardwood", 0.5)], [])
    assert score > 0.5
    assert score == 0.5 + 0.08 * 1.0 + 0.08 * 0.5


def test_red_flags_lower_condition():
    score = condition_from_findings([], [red_flag("water_stain", 1.0)])
    assert score < 0.5
    assert score == 0.5 - 0.15 * 1.0


def test_red_flags_outweigh_features_per_confidence():
    feat = condition_from_findings([feature("x", 1.0)], [])
    flag = condition_from_findings([], [red_flag("y", 1.0)])
    assert (feat - 0.5) < (0.5 - flag)  # a defect moves the needle more than a perk


def test_clamped_to_unit_interval():
    assert condition_from_findings([feature(f"f{i}", 1.0) for i in range(20)], []) == 1.0
    assert condition_from_findings([], [red_flag(f"r{i}", 1.0) for i in range(20)]) == 0.0


def test_deterministic_and_order_independent():
    a = condition_from_findings([feature("k", 0.9), feature("h", 0.4)], [red_flag("w", 0.6)])
    b = condition_from_findings([feature("h", 0.4), feature("k", 0.9)], [red_flag("w", 0.6)])
    assert a == b
