"""Vision-model interface + implementations.

The analyzer depends on the ``VisionModel`` protocol, not on any concrete model,
so the real Gemini call and the test fake are interchangeable (dependency
injection). The model's only job is: given a photo's bytes + its reference,
return raw structured findings (dicts shaped like the fixed schema). Validation
and review-routing live in the analyzer, not here.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from .schema import PhotoRef

logger = logging.getLogger(__name__)

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


# --------------------------------------------------------------------------- #
# Claude (Anthropic) vision model — the real implementation (R2).
# --------------------------------------------------------------------------- #
# Mirrors ``brain.llm.GeminiClient``: stdlib urllib (no SDK dependency), a
# key-gated factory, and a module-level circuit breaker so a bad / quota'd key
# doesn't add latency to the (capped, off-request-path) analysis task.
_ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")
_COOLDOWN_SECONDS = float(os.environ.get("ANTHROPIC_COOLDOWN_SECONDS", "600"))
_cooldown_until = 0.0

# transport(url, headers, body_bytes, timeout) -> parsed JSON dict. Injectable so
# tests drive the model with no network.
Transport = Callable[[str, Dict[str, str], bytes, float], Dict[str, Any]]


def _post_json(url: str, headers: Dict[str, str], body: bytes, timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed host)
        return json.loads(resp.read().decode("utf-8"))


def _sniff_media_type(image_bytes: bytes) -> str:
    """Best-effort image MIME from magic bytes; default JPEG."""
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:3] == b"GIF":
        return "image/gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _extract_tool_findings(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pull the ``findings`` array out of Claude's forced tool_use block.

    Structure-only: never falls back to reading prose text, so a model that
    ignores the tool yields no findings rather than hallucinated ones.
    """
    for block in response.get("content", []) or []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        if block.get("name") != FINDINGS_FUNCTION_SCHEMA["name"]:
            continue
        args = block.get("input")
        findings = args.get("findings") if isinstance(args, dict) else None
        if findings:
            return list(findings)
    return []


class ClaudeVisionModel:
    """``VisionModel`` backed by the Anthropic Messages API (forced tool use).

    The photo goes in as a base64 image block; Claude is forced to call
    ``report_property_findings`` against ``FINDINGS_FUNCTION_SCHEMA`` so the output
    is structured findings, never prose. Default model ``claude-opus-4-8`` (override
    with ``ANTHROPIC_MODEL``). No sampling params (removed on Opus 4.8).
    """

    def __init__(
        self,
        api_key: str,
        *,
        model_name: Optional[str] = None,
        transport: Optional[Transport] = None,
        timeout: float = 30.0,
        max_tokens: int = 1024,
    ) -> None:
        self._api_key = api_key
        self.model_name = model_name or _DEFAULT_MODEL
        self._transport = transport
        self._timeout = timeout
        self._max_tokens = max_tokens

    def build_request(self, image_bytes: bytes, ref: PhotoRef) -> Dict[str, Any]:
        """Construct the Messages API body (does not send)."""
        return {
            "model": self.model_name,
            "max_tokens": self._max_tokens,
            "tools": [
                {
                    "name": FINDINGS_FUNCTION_SCHEMA["name"],
                    "description": FINDINGS_FUNCTION_SCHEMA["description"],
                    "input_schema": FINDINGS_FUNCTION_SCHEMA["parameters"],
                }
            ],
            "tool_choice": {"type": "tool", "name": FINDINGS_FUNCTION_SCHEMA["name"]},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": _sniff_media_type(image_bytes),
                                "data": base64.standard_b64encode(image_bytes).decode("ascii"),
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "Identify value-features and visible red-flags in this "
                                "property photo. Call report_property_findings with "
                                "structured findings only. Do not write prose."
                            ),
                        },
                    ],
                }
            ],
        }

    def analyze_photo(self, image_bytes: bytes, ref: PhotoRef) -> List[Dict[str, Any]]:
        global _cooldown_until
        if time.monotonic() < _cooldown_until:
            raise RuntimeError("claude vision in cooldown after a recent failure")

        body = json.dumps(self.build_request(image_bytes, ref)).encode("utf-8")
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        transport = self._transport or _post_json
        try:
            data = transport(_ANTHROPIC_ENDPOINT, headers, body, self._timeout)
        except Exception:
            # Trip the breaker so a depleted / invalid key doesn't slow every photo.
            _cooldown_until = time.monotonic() + _COOLDOWN_SECONDS
            raise
        return _extract_tool_findings(data)


def claude_vision_model_or_none(
    *, transport: Optional[Transport] = None
) -> Optional["ClaudeVisionModel"]:
    """A ``ClaudeVisionModel`` when ``ANTHROPIC_API_KEY`` is set, else ``None``.

    ``None`` signals the caller to fall back to ``FakeVisionModel`` (the
    deterministic / offline path), so the system runs with no API key.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    try:
        return ClaudeVisionModel(key, transport=transport)
    except Exception as exc:  # pragma: no cover - construction is trivial
        logger.warning("Claude vision model unavailable: %s", exc)
        return None
