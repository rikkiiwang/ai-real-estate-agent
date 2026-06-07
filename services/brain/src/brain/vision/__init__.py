"""Property photo analysis (the Brain's vision pillar).

Emits structured, image-cited findings (value-features and red-flags) — never
prose. See ``schema`` for the fixed output contract, ``model`` for the injected
vision-model interface, and ``analyzer`` for the schema-valid analysis entry
point. Covers U4 (plan R3).
"""
from __future__ import annotations

from .schema import BBox, Finding, FindingKind, PhotoRef
from .model import (
    GeminiVisionModel,
    FakeVisionModel,
    VisionModel,
    ClaudeVisionModel,
    claude_vision_model_or_none,
)
from .analyzer import PhotoAnalyzer, AnalysisResult, DEFAULT_REDFLAG_CONFIDENCE
from .condition import condition_from_findings

__all__ = [
    "BBox",
    "Finding",
    "FindingKind",
    "PhotoRef",
    "VisionModel",
    "GeminiVisionModel",
    "FakeVisionModel",
    "ClaudeVisionModel",
    "claude_vision_model_or_none",
    "PhotoAnalyzer",
    "AnalysisResult",
    "DEFAULT_REDFLAG_CONFIDENCE",
    "condition_from_findings",
]
