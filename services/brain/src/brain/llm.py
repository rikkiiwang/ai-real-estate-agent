"""A tiny Gemini text client + a no-key factory.

Used by the LLM-backed generator and entailer. Stdlib-only (urllib) so it adds
no dependency. ``gemini_client_or_none()`` returns a client ONLY when
``GEMINI_API_KEY`` is set, so the brain falls back to its deterministic
generator/entailer everywhere else (tests, local runs without a key). Callers
must treat any failure as "LLM unavailable" and fall back — never raise into the
agent loop.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# Circuit breaker: after a quota/transport failure, stop calling Gemini for a
# cooldown so a quota-exhausted (HTTP 429) free key doesn't add ~1s latency to
# every agent turn. Auto-recovers when the window passes (e.g. the daily quota
# resets). Module-level so it's shared across the per-build client instances.
_COOLDOWN_SECONDS = float(os.environ.get("GEMINI_COOLDOWN_SECONDS", "600"))
_cooldown_until = 0.0

# gemini-2.0-flash has no "thinking" budget, so maxOutputTokens maps to actual
# output (2.5 models silently spend the budget thinking and return almost
# nothing). Override with GEMINI_MODEL if needed.
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


class GeminiClient:
    """Minimal text-generation client over the Gemini REST API."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def generate(self, prompt: str, *, temperature: float = 0.2, max_output_tokens: int = 512) -> str:
        global _cooldown_until
        if time.monotonic() < _cooldown_until:
            raise RuntimeError("gemini in cooldown after a recent failure")

        url = _ENDPOINT.format(model=self._model, key=self._api_key)
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_output_tokens},
        }
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310 (fixed host)
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Quota/rate-limit (or any HTTP error): trip the breaker so we stop
            # hammering a depleted key every turn.
            _cooldown_until = time.monotonic() + _COOLDOWN_SECONDS
            raise
        candidates = data.get("candidates") or []
        parts = (candidates[0].get("content", {}).get("parts") if candidates else None) or []
        text = "".join(p.get("text", "") for p in parts)
        return text.strip()


def gemini_client_or_none() -> Optional[GeminiClient]:
    """A GeminiClient when GEMINI_API_KEY is set, else None (deterministic path)."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    try:
        return GeminiClient(key)
    except Exception as exc:  # pragma: no cover - construction is trivial
        logger.warning("Gemini client unavailable: %s", exc)
        return None
