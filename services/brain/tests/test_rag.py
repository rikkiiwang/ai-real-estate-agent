"""U5 verification: RAG source-of-truth store + provenance-tagged retrieval.

All tests use ``InMemoryVectorStore`` + ``FakeEmbedder`` — no DB, no network.
They cover the U5 scenarios and the load-bearing contracts:

* ingest facts then retrieve for a matching address -> provenance-tagged
  evidence carrying stable ``source_id``s;
* a query with NO matching source -> EMPTY result (the "no source -> no claim"
  contract that drives the Critic);
* top-k ordering by similarity;
* a valuation run / photo findings are ingestible and retrievable as evidence;
* ``PgVectorStore`` is import-safe and constructing it does NOT connect.
"""
import numpy as np
import pytest

from brain.rag import (
    DEFAULT_DIM,
    Evidence,
    Fact,
    FakeEmbedder,
    InMemoryVectorStore,
    PgVectorStore,
    PROVENANCE_KINDS,
    RealEmbedder,
    Retriever,
    cosine_similarity,
    listing_field_facts,
    photo_finding_facts,
    valuation_facts,
)


ADDR = "123 Main St, Austin, TX"
OTHER_ADDR = "999 Elsewhere Ave, Austin, TX"


def make_retriever(min_score: float = 0.0) -> Retriever:
    embedder = FakeEmbedder()
    return Retriever(store=InMemoryVectorStore(embedder), embedder=embedder, min_score=min_score)


# --- schema / provenance -----------------------------------------------------

def test_fact_requires_stable_source_id_and_content():
    with pytest.raises(ValueError):
        Fact(source_id="  ", kind="tcad_appraisal", content="x")
    with pytest.raises(ValueError):
        Fact(source_id="s1", kind="tcad_appraisal", content="   ")


def test_fact_rejects_unknown_provenance_kind():
    with pytest.raises(ValueError):
        Fact(source_id="s1", kind="rumor", content="hearsay")  # type: ignore[arg-type]


def test_all_provenance_kinds_are_constructible():
    for kind in PROVENANCE_KINDS:
        f = Fact(source_id=f"s-{kind}", kind=kind, content="grounded fact")
        assert f.kind == kind


def test_evidence_exposes_provenance_accessors():
    fact = Fact(source_id="tcad-42", kind="tcad_appraisal", content="appraised at 500k")
    ev = Evidence(fact=fact, score=0.9)
    assert ev.source_id == "tcad-42"
    assert ev.kind == "tcad_appraisal"


# --- embedder ----------------------------------------------------------------

def test_fake_embedder_is_deterministic_and_fixed_dim():
    emb = FakeEmbedder()
    v1 = emb.embed("granite countertops kitchen")
    v2 = emb.embed("granite countertops kitchen")
    assert v1.shape == (DEFAULT_DIM,)
    assert np.allclose(v1, v2)  # deterministic, no randomness


def test_fake_embedder_related_text_more_similar_than_unrelated():
    emb = FakeEmbedder()
    base = emb.embed("three bedroom two bath house")
    related = emb.embed("three bedroom house")
    unrelated = emb.embed("commercial warehouse zoning permit")
    assert cosine_similarity(base, related) > cosine_similarity(base, unrelated)


def test_real_embedder_refuses_to_run_without_client_and_never_networks():
    emb = RealEmbedder()  # no client injected
    # build_request must not send anything; just builds a payload.
    req = emb.build_request("some text")
    assert req["input"] == ["some text"]
    with pytest.raises(RuntimeError):
        emb.embed("some text")


# --- ingest + retrieve: provenance-tagged evidence for a matching address -----

def test_ingest_then_retrieve_returns_provenance_tagged_evidence():
    r = make_retriever()
    r.ingest(
        Fact(
            source_id="tcad-100",
            kind="tcad_appraisal",
            content="TCAD appraised value 525000 dollars three bedroom",
            address=ADDR,
        )
    )

    evidence = r.retrieve("appraised value three bedroom", address=ADDR)

    assert evidence, "a matching source must return evidence"
    top = evidence[0]
    assert top.source_id == "tcad-100"  # stable source id carried through
    assert top.kind == "tcad_appraisal"  # provenance tag present
    assert top.fact.address == ADDR


def test_address_scope_excludes_other_addresses():
    r = make_retriever()
    r.ingest(Fact(source_id="a", kind="listing_field", content="four bedroom pool", address=ADDR))
    r.ingest(
        Fact(source_id="b", kind="listing_field", content="four bedroom pool", address=OTHER_ADDR)
    )

    evidence = r.retrieve("four bedroom pool", address=ADDR)

    assert [e.source_id for e in evidence] == ["a"]  # scope filters out OTHER_ADDR


# --- no source -> EMPTY (the "no source -> no claim" contract) ----------------

def test_query_with_no_stored_source_returns_empty():
    r = make_retriever()
    assert r.retrieve("anything at all", address=ADDR) == []
    assert r.has_support("anything at all", address=ADDR) is False


def test_query_for_unscoped_address_returns_empty():
    r = make_retriever()
    r.ingest(Fact(source_id="a", kind="comp_sale", content="sold for 600k", address=ADDR))
    # A different address has no source -> empty, even though the store is non-empty.
    assert r.retrieve("sold for 600k", address=OTHER_ADDR) == []


def test_min_score_floor_treats_weak_match_as_no_source():
    # With a high min_score, an unrelated query has no support.
    r = make_retriever(min_score=0.99)
    r.ingest(Fact(source_id="a", kind="comp_sale", content="granite countertops", address=ADDR))
    assert r.retrieve("flood zone insurance premium", address=ADDR) == []


def test_blank_claim_returns_empty():
    r = make_retriever()
    r.ingest(Fact(source_id="a", kind="comp_sale", content="sold for 600k", address=ADDR))
    assert r.retrieve("   ", address=ADDR) == []


# --- top-k ordering by similarity --------------------------------------------

def test_retrieve_orders_by_similarity_and_respects_top_k():
    r = make_retriever()
    r.ingest(Fact(source_id="exact", kind="listing_field", content="granite countertops kitchen", address=ADDR))
    r.ingest(Fact(source_id="partial", kind="listing_field", content="granite countertops", address=ADDR))
    r.ingest(Fact(source_id="far", kind="listing_field", content="detached garage driveway", address=ADDR))

    evidence = r.retrieve("granite countertops kitchen", address=ADDR, top_k=2)

    assert len(evidence) == 2  # top_k respected
    # Descending similarity; the exact match ranks above the partial.
    assert evidence[0].source_id == "exact"
    assert evidence[1].source_id == "partial"
    scores = [e.score for e in evidence]
    assert scores == sorted(scores, reverse=True)


# --- upsert: re-ingesting a source_id replaces, never duplicates --------------

def test_reingest_same_source_id_upserts():
    r = make_retriever()
    store = r.store
    r.ingest(Fact(source_id="v1", kind="valuation_run", content="value 500k", address=ADDR))
    r.ingest(Fact(source_id="v1", kind="valuation_run", content="value 525k revised", address=ADDR))
    assert len(store) == 1  # replaced, not duplicated
    evidence = r.retrieve("value revised", address=ADDR)
    assert evidence[0].fact.content == "value 525k revised"


# --- integration: Brain outputs become retrievable evidence ------------------

class _StubVFact:
    def __init__(self, source_id, kind, description, contribution):
        self.source_id = source_id
        self.kind = kind
        self.description = description
        self.contribution = contribution


class _StubValuation:
    def __init__(self, sufficient_data, estimate=0.0, low=0.0, high=0.0, facts=()):
        self.sufficient_data = sufficient_data
        self.estimate = estimate
        self.low = low
        self.high = high
        self.facts = list(facts)


def test_valuation_run_is_ingestible_and_retrievable():
    r = make_retriever()
    valuation = _StubValuation(
        sufficient_data=True,
        estimate=525000.0,
        low=500000.0,
        high=550000.0,
        facts=[_StubVFact("tcad-1", "feature:sqft", "Living area (sqft)", 120000.0)],
    )
    facts = valuation_facts(ADDR, valuation, run_id="run-7")
    r.ingest_many(facts)

    evidence = r.retrieve("estimated value range", address=ADDR)
    assert evidence
    assert any(e.kind == "valuation_run" for e in evidence)
    assert any(e.source_id == "run-7:estimate" for e in evidence)


def test_insufficient_valuation_yields_no_facts():
    assert valuation_facts(ADDR, _StubValuation(sufficient_data=False), run_id="run-8") == []


class _StubFinding:
    def __init__(self, label, confidence, evidence_photo_id, kind="feature"):
        self.label = label
        self.confidence = confidence
        self.evidence_photo_id = evidence_photo_id
        self.kind = kind


def test_photo_findings_are_ingestible_and_cite_the_photo():
    r = make_retriever()
    findings = [_StubFinding("granite_countertops", 0.95, "kitchen-01")]
    facts = photo_finding_facts(ADDR, findings)
    r.ingest_many(facts)

    evidence = r.retrieve("granite_countertops", address=ADDR)
    assert evidence
    ev = evidence[0]
    assert ev.kind == "photo_finding"
    assert ev.fact.metadata["photo_id"] == "kitchen-01"  # cited to source photo


def test_listing_field_facts_one_per_field_with_stable_ids():
    facts = listing_field_facts(ADDR, {"beds": 3, "baths": 2}, listing_id="L1")
    ids = {f.source_id for f in facts}
    assert ids == {"listing:L1:beds", "listing:L1:baths"}
    assert all(f.kind == "listing_field" for f in facts)


# --- PgVectorStore: import-safe, lazily-connecting (NO DB required) -----------

def test_pgvector_store_construct_does_not_connect():
    # Constructing with a deliberately-unreachable DSN must NOT raise: no
    # connection is opened at construction time (lazy connect).
    store = PgVectorStore(
        dsn="postgresql://nobody@127.0.0.1:1/doesnotexist",
        embedder=FakeEmbedder(),
    )
    assert store is not None
    # The connection is still unopened.
    assert store._connection is None


def test_pgvector_store_only_connects_on_use():
    store = PgVectorStore(
        dsn="postgresql://nobody@127.0.0.1:1/doesnotexist",
        embedder=FakeEmbedder(),
    )
    # First real use attempts a connection, which fails against the bogus DSN.
    # The point: the failure happens at USE time, not import/construct time.
    with pytest.raises(Exception):
        store.ingest(Fact(source_id="s1", kind="comp_sale", content="x", address=ADDR))


def test_importing_rag_does_not_require_postgres():
    # If importing the package or referencing PgVectorStore needed a live DB or
    # the import of psycopg/pgvector at module load, the import at the top of
    # this file would already have failed. Assert the symbol is usable.
    assert PgVectorStore.__name__ == "PgVectorStore"
