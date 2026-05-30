"""Property photo analysis (the Brain's vision pillar).

Emits structured, image-cited findings (value-features and red-flags) — never
prose. See ``schema`` for the fixed output contract, ``model`` for the injected
vision-model interface, and ``analyzer`` for the schema-valid analysis entry
point. Covers U4 (plan R3).
"""
from __future__ import annotations

from .schema import BBox, Finding, FindingKind, PhotoRef
from .model import GeminiVisionModel, FakeVisionModel, VisionModel
from .analyzer import PhotoAnalyzer, AnalysisResult, DEFAULT_REDFLAG_CONFIDENCE

__all__ = [
    "BBox",
    "Finding",
    "FindingKind",
    "PhotoRef",
    "VisionModel",
    "GeminiVisionModel",
    "FakeVisionModel",
    "PhotoAnalyzer",
    "AnalysisResult",
    "DEFAULT_REDFLAG_CONFIDENCE",
]
