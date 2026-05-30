"""Embedder abstraction: turn text into a fixed-dimension vector.

The store and retriever depend on the :class:`Embedder` protocol, not on any
concrete model, so the deterministic test fake and a real network-backed
embedder are interchangeable (dependency injection).

* :class:`FakeEmbedder` hashes text into a fixed-dim L2-normalized vector with no
  network and no randomness — identical text always yields the identical vector,
  so retrieval is fully hermetic and reproducible in tests.
* :class:`RealEmbedder` is a thin hook around an injected embedding client; it
  builds the request and delegates, and refuses to run without a client (it
  never reaches the network on its own).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Protocol, runtime_checkable

import numpy as np

# Default embedding width. Small enough to be cheap in tests, wide enough that
# hashed tokens rarely collide. Real models override via their own dim.
DEFAULT_DIM: int = 256


def _l2_normalize(vector: np.ndarray) -> np.ndarray:
    """Return ``vector`` scaled to unit L2 norm (zero vector left unchanged).

    Normalizing here makes cosine similarity reduce to a dot product downstream.
    """
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        return vector
    return vector / norm


@runtime_checkable
class Embedder(Protocol):
    """Maps text to a fixed-length float vector.

    Implementations must expose a stable ``dim`` and return a 1-D ``np.ndarray``
    of that length. The same input should map to the same vector (determinism is
    required of test doubles, expected of real models for caching).
    """

    dim: int

    def embed(self, text: str) -> np.ndarray:
        ...


@dataclass
class FakeEmbedder:
    """Deterministic, network-free embedder for hermetic tests + local dev.

    Each whitespace token is hashed (SHA-256) into a bucket of a ``dim``-wide
    vector and accumulated, then the vector is L2-normalized. Texts sharing
    tokens land near each other (positive cosine), unrelated texts stay near
    orthogonal — enough structure to exercise top-k ordering and the no-match
    contract without a model. Pure function of the input: no randomness, no I/O.
    """

    dim: int = DEFAULT_DIM

    def embed(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float64)
        tokens = text.lower().split()
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            # First 8 bytes -> bucket; next 8 -> signed weight, so distinct
            # tokens push different dimensions in different directions.
            bucket = int.from_bytes(digest[:8], "big") % self.dim
            weight = (int.from_bytes(digest[8:16], "big") % 2000) / 1000.0 - 1.0
            vector[bucket] += weight
        return _l2_normalize(vector)


@dataclass
class RealEmbedder:
    """Thin hook around an injected embedding client — never calls a network alone.

    A later unit wires a real embedding client (the callable that, given a list
    of texts, returns their vectors). With no client injected, :meth:`embed`
    refuses to run rather than reaching out, mirroring ``GeminiVisionModel``'s
    discipline in the vision package. ``build_request`` exposes the payload for
    inspection/testing without sending it.
    """

    client: Optional[Callable[[List[str]], List[List[float]]]] = None
    model_name: str = "text-embedding-3-small"
    dim: int = 1536

    def build_request(self, text: str) -> dict:
        """Construct the embedding request payload (does not send)."""
        return {"model": self.model_name, "input": [text]}

    def embed(self, text: str) -> np.ndarray:
        if self.client is None:
            raise RuntimeError(
                "RealEmbedder has no embedding client injected; provide one to "
                "run, or use FakeEmbedder in tests."
            )
        vectors = self.client([text])
        return _l2_normalize(np.asarray(vectors[0], dtype=np.float64))


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two vectors, robust to non-normalized inputs."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)
