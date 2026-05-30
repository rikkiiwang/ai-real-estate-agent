"""Vision-model interface + implementations.

The analyzer depends on the ``VisionModel`` protocol, not on any concrete model,
so the real Gemini call and the test fake are interchangeable (dependency
injection). The model's only job is: given a photo's bytes + its reference,
return raw structured findings (dicts shaped like the fixed schema). Validation
and review-routing live in the analyzer, not here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .schema import PhotoRef

# The structured-output / function-calling schema we hand to the model. A model
# returns a list of objects shaped like this; the analyzer parses + validates.
FINDINGS_FUNCTION_SCHEMA: Dict[str, Any] = {
    "name": "report_property_findings",
    "description": (
        "Report value-features and visible red-flags seen in a single property "
        "photo as structured findings. Do not write prose or descriptions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["feature", "red_flag"]},
                        "label": {
                            "type": "string",
                            "description": "stable machine token, e.g. granite_countertops",
                        },
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "bbox": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "width": {"type": "number"},
                                "height": {"type": "number"},
                            },
                            "required": ["x", "y", "width", "height"],
                        },
                    },
                    "required": ["kind", "label", "confidence"],
                },
            }
        },
        "required": ["findings"],
    },
}


@runtime_checkable
class VisionModel(Protocol):
    """A model that maps one photo to raw structured findings.

    Implementations must return a list of plain dicts shaped like the schema
    items (``kind``, ``label``, ``confidence``, optional ``bbox``). They must NOT
    return prose. ``evidence_photo_id`` is stamped by the analyzer from ``ref``,
    so models may omit it.
    """

    def analyze_photo(self, image_bytes: bytes, ref: PhotoRef) -> List[Dict[str, Any]]:
        ...


class GeminiVisionModel:
    """Thin wrapper that constructs the Gemini structured-output request.

    No API key is available in this environment, so this builds (and exposes for
    inspection) the request without sending it; ``analyze_photo`` requires an
    injected client to actually run. A later unit wires a real ``google-genai``
    client. The point here is the structured-output discipline: function-calling
    against ``FINDINGS_FUNCTION_SCHEMA``, never free-text.
    """

    def __init__(
        self,
        client: Optional[Any] = None,
        *,
        model_name: str = "gemini-1.5-pro",
    ) -> None:
        self._client = client
        self.model_name = model_name

    def build_request(self, image_bytes: bytes, ref: PhotoRef) -> Dict[str, Any]:
        """Construct the structured-output request payload (does not send)."""
        return {
            "model": self.model_name,
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_bytes,
                            }
                        },
                        {
                            "text": (
                                "Identify value-features and visible red-flags in "
                                "this property photo. Call "
                                "report_property_findings with structured findings "
                                "only. Do not write prose."
                            )
                        },
                    ],
                }
            ],
            "tools": [{"function_declarations": [FINDINGS_FUNCTION_SCHEMA]}],
            "tool_config": {"function_calling_config": {"mode": "ANY"}},
            "photo_id": ref.photo_id,
        }

    def analyze_photo(self, image_bytes: bytes, ref: PhotoRef) -> List[Dict[str, Any]]:
        if self._client is None:
            raise RuntimeError(
                "GeminiVisionModel has no client injected; provide a google-genai "
                "client to run, or use FakeVisionModel in tests."
            )
        request = self.build_request(image_bytes, ref)
        response = self._client.generate_content(**request)
        return _extract_function_call_findings(response)


def _extract_function_call_findings(response: Any) -> List[Dict[str, Any]]:
    """Pull the ``findings`` array out of a Gemini function-call response."""
    # Defensive, structure-only parse — never falls back to reading prose text.
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            call = getattr(part, "function_call", None)
            if call is None:
                continue
            args = getattr(call, "args", None) or {}
            findings = args.get("findings") if isinstance(args, dict) else None
            if findings:
                return list(findings)
    return []


@dataclass
class FakeVisionModel:
    """Test double that returns canned structured findings per photo.

    Map ``photo_id -> list[finding-dict]``. Photos with no entry return ``[]``
    (an ambiguous/empty photo yields no findings, never invented prose).
    """

    canned: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    calls: List[str] = field(default_factory=list)

    def analyze_photo(self, image_bytes: bytes, ref: PhotoRef) -> List[Dict[str, Any]]:
        self.calls.append(ref.photo_id)
        # Return copies so callers can't mutate the canned fixtures.
        return [dict(f) for f in self.canned.get(ref.photo_id, [])]
