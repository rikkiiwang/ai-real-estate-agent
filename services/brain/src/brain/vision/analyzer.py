"""Photo analyzer: turn photo references into schema-valid findings.

The analyzer drives an injected :class:`~brain.vision.model.VisionModel` over a
set of photos, validates every returned object against the fixed schema, and
splits the results:

* ``features`` feed downstream (the AVM in U3, the Critic in U6) as image-cited
  claims — exposed as a clean return type here; not wired into other modules.
* ``red_flags`` are *never* asserted as customer claims. Any red_flag, and any
  finding below the confidence threshold, routes to ``needs_review`` for a human.

No prose is ever produced — only structured :class:`~brain.vision.schema.Finding`
objects. Corrupt or missing images are handled gracefully (recorded as errors,
never crash the batch).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .model import VisionModel
from .schema import BBox, Finding, PhotoRef

# Below this confidence a finding is not asserted; it routes to human review.
# Conservative by design: red-flags route to review regardless of confidence.
DEFAULT_REDFLAG_CONFIDENCE: float = 0.6


@dataclass
class PhotoError:
    """A photo that could not be analyzed (corrupt/missing/model failure)."""

    photo_id: str
    reason: str


@dataclass
class AnalysisResult:
    """Clean, structured output of a photo-analysis batch.

    ``features`` are confident value-features safe to feed downstream.
    ``needs_review`` holds every red_flag plus any low-confidence finding — these
    are *candidate* findings for a human, not asserted claims.
    ``errors`` records photos that failed to analyze.
    """

    features: List[Finding] = field(default_factory=list)
    needs_review: List[Finding] = field(default_factory=list)
    errors: List[PhotoError] = field(default_factory=list)

    @property
    def all_findings(self) -> List[Finding]:
        return [*self.features, *self.needs_review]


def _coerce_bbox(raw: Any) -> Optional[BBox]:
    if raw is None:
        return None
    if isinstance(raw, BBox):
        return raw
    if not isinstance(raw, dict):
        raise ValueError("bbox must be an object")
    return BBox(
        x=float(raw["x"]),
        y=float(raw["y"]),
        width=float(raw["width"]),
        height=float(raw["height"]),
    )


def _coerce_finding(raw: Dict[str, Any], photo_id: str) -> Finding:
    """Build a validated :class:`Finding`, stamping the evidence photo id.

    The model's ``evidence_photo_id`` (if any) is ignored in favor of the photo
    actually analyzed, so a finding can never be mis-cited to another image.
    """
    return Finding(
        kind=raw["kind"],
        label=raw["label"],
        confidence=float(raw["confidence"]),
        evidence_photo_id=photo_id,
        bbox=_coerce_bbox(raw.get("bbox")),
    )


class PhotoAnalyzer:
    """Analyze photos into schema-valid, routed findings via an injected model."""

    def __init__(
        self,
        model: VisionModel,
        *,
        review_confidence_threshold: float = DEFAULT_REDFLAG_CONFIDENCE,
    ) -> None:
        if not 0.0 <= review_confidence_threshold <= 1.0:
            raise ValueError("review_confidence_threshold must be in [0, 1]")
        self._model = model
        self.review_confidence_threshold = review_confidence_threshold

    def analyze(
        self,
        photos: Iterable[tuple[PhotoRef, Optional[bytes]]],
    ) -> AnalysisResult:
        """Analyze ``(ref, image_bytes)`` pairs into a routed result.

        ``image_bytes`` of ``None`` or empty is treated as a missing image and
        recorded as an error rather than analyzed. Any per-photo failure (model
        error, malformed finding) is captured in ``errors`` and does not abort
        the rest of the batch.
        """
        result = AnalysisResult()
        for ref, image_bytes in photos:
            self._analyze_one(ref, image_bytes, result)
        return result

    def _analyze_one(
        self,
        ref: PhotoRef,
        image_bytes: Optional[bytes],
        result: AnalysisResult,
    ) -> None:
        if not image_bytes:
            result.errors.append(
                PhotoError(photo_id=ref.photo_id, reason="missing or empty image")
            )
            return
        try:
            raw_findings = self._model.analyze_photo(image_bytes, ref)
        except Exception as exc:  # graceful: one bad photo never kills the batch
            result.errors.append(
                PhotoError(photo_id=ref.photo_id, reason=f"model error: {exc}")
            )
            return

        for raw in raw_findings:
            try:
                finding = _coerce_finding(raw, ref.photo_id)
            except (KeyError, ValueError, TypeError) as exc:
                result.errors.append(
                    PhotoError(
                        photo_id=ref.photo_id,
                        reason=f"invalid finding from model: {exc}",
                    )
                )
                continue
            self._route(finding, result)

    def _route(self, finding: Finding, result: AnalysisResult) -> None:
        # Red-flags are never asserted as customer claims; always human-review.
        # Low-confidence findings of any kind also route to review, not downstream.
        if finding.is_red_flag or finding.confidence < self.review_confidence_threshold:
            result.needs_review.append(finding)
        else:
            result.features.append(finding)
