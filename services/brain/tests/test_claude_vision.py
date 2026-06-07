"""ClaudeVisionModel + key-gated factory tests (no network).

A fake transport drives the model end to end, so these assert the request shape
and the structure-only response parse without an API key or HTTP.
"""
from __future__ import annotations

import base64

import pytest

from brain.vision import ClaudeVisionModel, claude_vision_model_or_none
from brain.vision.model import _extract_tool_findings, _sniff_media_type
from brain.vision.schema import PhotoRef

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def _tool_response(findings):
    return {
        "content": [
            {"type": "text", "text": "ignored prose"},
            {"type": "tool_use", "name": "report_property_findings", "input": {"findings": findings}},
        ]
    }


def test_build_request_forces_the_findings_tool_with_a_base64_image():
    model = ClaudeVisionModel("sk-test", model_name="claude-opus-4-8")
    req = model.build_request(JPEG_BYTES, PhotoRef(photo_id="p1"))

    assert req["model"] == "claude-opus-4-8"
    assert req["tool_choice"] == {"type": "tool", "name": "report_property_findings"}
    assert req["tools"][0]["name"] == "report_property_findings"
    assert "input_schema" in req["tools"][0]  # Anthropic shape, not Gemini "parameters"
    # no sampling params (removed on Opus 4.8)
    assert "temperature" not in req and "top_p" not in req and "top_k" not in req

    image_block = req["messages"][0]["content"][0]
    assert image_block["type"] == "image"
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert image_block["source"]["data"] == base64.standard_b64encode(JPEG_BYTES).decode("ascii")


def test_model_name_defaults_to_opus_and_is_overridable():
    assert ClaudeVisionModel("sk-test").model_name == "claude-opus-4-8"
    assert ClaudeVisionModel("sk-test", model_name="claude-haiku-4-5").model_name == "claude-haiku-4-5"


def test_media_type_sniffing():
    assert _sniff_media_type(PNG_BYTES) == "image/png"
    assert _sniff_media_type(JPEG_BYTES) == "image/jpeg"
    assert _sniff_media_type(b"random") == "image/jpeg"  # default


def test_analyze_photo_returns_findings_from_the_tool_block():
    captured = {}

    def transport(url, headers, body, timeout):
        captured["url"] = url
        captured["headers"] = headers
        return _tool_response([
            {"kind": "feature", "label": "updated_kitchen", "confidence": 0.9},
            {"kind": "red_flag", "label": "water_stain_ceiling", "confidence": 0.7},
        ])

    model = ClaudeVisionModel("sk-test", transport=transport)
    findings = model.analyze_photo(JPEG_BYTES, PhotoRef(photo_id="p1"))

    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"]["x-api-key"] == "sk-test"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert [f["label"] for f in findings] == ["updated_kitchen", "water_stain_ceiling"]


def test_response_without_a_tool_block_yields_no_findings():
    assert _extract_tool_findings({"content": [{"type": "text", "text": "no tool call"}]}) == []
    assert _extract_tool_findings({}) == []


def test_factory_is_key_gated(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert claude_vision_model_or_none() is None

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-live")
    model = claude_vision_model_or_none()
    assert isinstance(model, ClaudeVisionModel)
