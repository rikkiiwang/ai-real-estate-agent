"""Source-of-truth store: the persistence behind RAG retrieval.

A :class:`SourceStore` ingests provenance-bearing :class:`~brain.rag.schema.Fact`
records and, given a query embedding, returns the most similar facts as
:class:`~brain.rag.schema.Evidence`. Two implementations share the interface:

* :class:`InMemoryVectorStore` — cosine-similarity search over embeddings held in
  a list (numpy). Used for tests and local dev: no DB, fully deterministic.
* :class:`PgVectorStore` — Postgres + ``pgvector`` for prod. It is IMPORT-SAFE
  and connects LAZILY: constructing one never touches the network, so the test
  suite never requires a live Postgres. The connection opens only on first use.

Both key facts by their stable ``source_id``: re-ingesting the same id REPLACES
the prior fact (upsert), so a refreshed valuation run or listing field never
duplicates evidence. Address scope, when given on a query, filters candidates to
that address before ranking.
"""
from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

import numpy as np

from .embedder import Embedder
from .schema import Evidence, Fact


def _normalize_address(address: Optional[str]) -> Optional[str]:
    """Canonicalize an address for scope matching (case/space-insensitive)."""
    if address is None:
        return None
    return " ".join(address.lower().split())


@runtime_checkable
class SourceStore(Protocol):
    """Persistence + similarity-search interface the retriever depends on.

    Implementations embed each fact's ``content`` via the injected
    :class:`~brain.rag.embedder.Embedder` on ingest, and rank candidates against
    a query embedding. A query whose ``address`` scope (or content) matches no
    stored fact returns an EMPTY list — the contract that drives the Critic's
    "no source -> no claim" rule.
    """

    def ingest(self, fact: Fact) -> None:
        """Upsert one fact (keyed by ``source_id``) into the store."""
        ...

    def ingest_many(self, facts: List[Fact]) -> None:
        """Upsert many facts."""
        ...

    def search(
        self,
        query_embedding: np.ndarray,
        *,
        top_k: int,
        address: Optional[str] = None,
    ) -> List[Evidence]:
        """Return up to ``top_k`` evidence ordered by descending similarity."""
        ...

    def __len__(self) -> int:
        ...


class InMemoryVectorStore:
    """Cosine-similarity source store backed by in-memory numpy vectors.

    Hermetic and deterministic — the default for tests and local dev. Facts are
    embedded on ingest and stored alongside their unit-normalized vectors;
    :meth:`search` ranks by dot product (cosine, since vectors are normalized).
    """

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        # source_id -> (Fact, normalized embedding). Dict keying gives upsert.
        self._facts: dict[str, Fact] = {}
        self._vectors: dict[str, np.ndarray] = {}

    def ingest(self, fact: Fact) -> None:
        vector = np.asarray(self._embedder.embed(fact.content), dtype=np.float64)
        norm = float(np.linalg.norm(vector))
        if norm != 0.0:
            vector = vector / norm
        self._facts[fact.source_id] = fact
        self._vectors[fact.source_id] = vector

    def ingest_many(self, facts: List[Fact]) -> None:
        for fact in facts:
            self.ingest(fact)

    def search(
        self,
        query_embedding: np.ndarray,
        *,
        top_k: int,
        address: Optional[str] = None,
    ) -> List[Evidence]:
        if top_k <= 0 or not self._facts:
            return []
        query = np.asarray(query_embedding, dtype=np.float64)
        qnorm = float(np.linalg.norm(query))
        if qnorm != 0.0:
            query = query / qnorm

        scope = _normalize_address(address)
        scored: List[Evidence] = []
        for source_id, fact in self._facts.items():
            if scope is not None and _normalize_address(fact.address) != scope:
                continue
            score = float(np.dot(query, self._vectors[source_id]))
            scored.append(Evidence(fact=fact, score=score))

        scored.sort(key=lambda e: e.score, reverse=True)
        return scored[:top_k]

    def __len__(self) -> int:
        return len(self._facts)


# DDL the pgvector store ensures on first connection. Kept here so the prod
# schema is visible without a DB. ``embedding`` width is the embedder's dim.
_CREATE_TABLE_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS rag_facts (
    source_id  TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    content    TEXT NOT NULL,
    address    TEXT,
    metadata   JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding  VECTOR(%(dim)s) NOT NULL
);
"""


class PgVectorStore:
    """Postgres + pgvector source store for production.

    IMPORT-SAFE and LAZILY-CONNECTING: constructing this object does NOT open a
    connection or touch the network — the DSN is merely held. The connection is
    established on first real use (:meth:`ingest`/:meth:`search`) via
    :meth:`_conn`, so importing or instantiating the class in a DB-less test
    environment is safe. ``psycopg`` and ``pgvector`` are imported lazily inside
    methods for the same reason: the module imports without a running Postgres.
    """

    def __init__(self, dsn: str, embedder: Embedder, *, table: str = "rag_facts") -> None:
        self._dsn = dsn
        self._embedder = embedder
        self._table = table
        self._connection = None  # opened lazily on first use
        self._initialized = False

    def _conn(self):
        """Open (once) and return the live connection. Network happens HERE."""
        if self._connection is None:
            import psycopg  # lazy: import only when a real connection is needed
            from pgvector.psycopg import register_vector

            self._connection = psycopg.connect(self._dsn)
            register_vector(self._connection)
            self._ensure_schema()
        return self._connection

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._connection.cursor() as cur:
            cur.execute(_CREATE_TABLE_SQL % {"dim": int(self._embedder.dim)})
        self._connection.commit()
        self._initialized = True

    def ingest(self, fact: Fact) -> None:
        import json

        vector = np.asarray(self._embedder.embed(fact.content), dtype=np.float64)
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._table}
                    (source_id, kind, content, address, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_id) DO UPDATE SET
                    kind = EXCLUDED.kind,
                    content = EXCLUDED.content,
                    address = EXCLUDED.address,
                    metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding
                """,
                (
                    fact.source_id,
                    fact.kind,
                    fact.content,
                    fact.address,
                    json.dumps(fact.metadata),
                    vector,
                ),
            )
        conn.commit()

    def ingest_many(self, facts: List[Fact]) -> None:
        for fact in facts:
            self.ingest(fact)

    def search(
        self,
        query_embedding: np.ndarray,
        *,
        top_k: int,
        address: Optional[str] = None,
    ) -> List[Evidence]:
        if top_k <= 0:
            return []
        query = np.asarray(query_embedding, dtype=np.float64)
        conn = self._conn()
        # Cosine distance operator (<=>); similarity = 1 - distance. Address
        # scope, when given, filters candidates before ranking. ``query``
        # appears twice (score expr + ORDER BY), so params are laid out to match
        # the placeholder order in the statement.
        where = ""
        params: list = [query]  # score expression
        if address is not None:
            where = "WHERE lower(address) = lower(%s)"
            params.append(address)
        params.append(query)  # ORDER BY
        params.append(int(top_k))  # LIMIT
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT source_id, kind, content, address, metadata,
                       1 - (embedding <=> %s) AS score
                FROM {self._table}
                {where}
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
        results: List[Evidence] = []
        for source_id, kind, content, addr, metadata, score in rows:
            fact = Fact(
                source_id=source_id,
                kind=kind,
                content=content,
                address=addr,
                metadata=dict(metadata or {}),
            )
            results.append(Evidence(fact=fact, score=float(score)))
        return results

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
            self._initialized = False

    def __len__(self) -> int:
        conn = self._conn()
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {self._table}")
            (count,) = cur.fetchone()
        return int(count)
