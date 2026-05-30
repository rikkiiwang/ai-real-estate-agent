"""Fixed structured-output schema for per-photo vision findings.

The analyzer and every ``VisionModel`` implementation speak this schema and
nothing else — no prose. A finding is either a value ``feature`` (feeds the AVM
in U3 and flows through the Critic in U6 as an image-cited claim) or a
``red_flag`` (a visible defect that routes to human review). Each finding cites
the photo it came from and carries a per-finding confidence in ``[0, 1]``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

# A finding is exactly one of these kinds; the analyzer never emits anything else.
FindingKind = Literal["feature", "red_flag"]


@dataclass(frozen=True)
class PhotoRef:
    """A stable reference to a source photo a finding is cited against."""

    photo_id: str
    # Optional locator for retrieval/provenance (URL, object key, fixture path).
    uri: Optional[str] = None


@dataclass(frozen=True)
class BBox:
    """Normalized bounding box in ``[0, 1]`` image coordinates (x,y top-left)."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        for name, value in (
            ("x", self.x),
            ("y", self.y),
            ("width", self.width),
            ("height", self.height),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"bbox {name}={value!r} out of normalized range [0, 1]")
        if self.x + self.width > 1.0 + 1e-9 or self.y + self.height > 1.0 + 1e-9:
            raise ValueError("bbox extends past the image bounds")


@dataclass(frozen=True)
class Finding:
    """One structured, image-cited vision finding.

    ``label`` is a stable machine token (e.g. ``"granite_countertops"``,
    ``"water_stain_ceiling"``), never a free-text sentence.
    """

    kind: FindingKind
    label: str
    confidence: float
    evidence_photo_id: str
    bbox: Optional[BBox] = None

    def __post_init__(self) -> None:
        if self.kind not in ("feature", "red_flag"):
            raise ValueError(f"invalid finding kind: {self.kind!r}")
        if not self.label or not self.label.strip():
            raise ValueError("finding label must be a non-empty token")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence {self.confidence!r} out of range [0, 1]")
        if not self.evidence_photo_id:
            raise ValueError("finding must cite an evidence_photo_id")

    @property
    def is_feature(self) -> bool:
        return self.kind == "feature"

    @property
    def is_red_flag(self) -> bool:
        return self.kind == "red_flag"
