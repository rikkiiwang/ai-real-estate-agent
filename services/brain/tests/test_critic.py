"""U6 verification: the Critic / claim-verification rail (covers AE1, R11).

All tests are hermetic — RAG ``InMemoryVectorStore`` + ``FakeEmbedder`` for
retrieval and the deterministic ``FakeEntailer`` for labeling; no DB, no network.
They exercise the load-bearing safety contract:

* a draft claim ENTAILED by an ingested fact passes WITH a citation;
* an unsupported claim (no source) is BLOCKED, not sent;
* a CONTRADICTED claim escalates;
* a partially-supported multi-claim draft strips the unsupported claim and keeps
  the rest;
* the result carries per-claim source decisions (loggable to the U9 audit table);
* the decomposer and entailer contracts the Critic rests on.
"""
import pytest

from brain.rag import Fact, FakeEmbedder, InMemoryVectorStore, Retriever

from brain.lawyer.critic import Critic, VerificationResult
from brain.lawyer.decompose import decompose, split_claims
from brain.lawyer.entailment import (
    Entailer,
    FakeEntailer,
    Label,
    RealEntailer,
    Verdict,
)


ADDR = "123 Main St, Austin, TX"


def build_critic(facts=(), *, fixtures=None, threshold=0.6) -> Critic:
    """Critic over an in-memory RAG store seeded with ``facts`` + a FakeEntailer."""
    embedder = FakeEmbedder()
    store = InMemoryVectorStore(embedder)
    for fact in facts:
        store.ingest(fact)
    retriever = Retriever(store=store, embedder=embedder, min_score=0.1)
    entailer = FakeEntailer(fixtures=fixtures or {})
    return Critic(retriever=retriever, entailer=entailer, threshold=threshold)


def fact(source_id: str, content: str, kind: str = "tcad_appraisal") -> Fact:
    return Fact(source_id=source_id, kind=kind, content=content, address=ADDR)


# --- decompose ---------------------------------------------------------------

def test_split_claims_empty_draft_yields_no_claims():
    assert split_claims("   ") == []
    assert decompose("") == []


def test_decompose_splits_sentences_and_conjunctions():
    draft = "The home has three bedrooms. It has a renovated kitchen and a pool."
    claims = [c.text for c in decompose(draft)]
    assert len(claims) == 3
    assert "renovated kitchen" in claims[1]
    assert "pool" in claims[2]
    # indices preserve original ordering for the audit log.
    assert [c.index for c in decompose(draft)] == [0, 1, 2]


# --- entailment contract (the load-bearing safety guarantee) -----------------

def test_fake_entailer_empty_evidence_is_baseless():
    verdict = FakeEntailer().entail("recently renovated kitchen", [])
    assert verdict.label is Label.BASELESS
    assert verdict.score == 0.0
    assert verdict.evidence is None


def test_fake_entailer_overlap_entails_with_score_and_citation():
    embedder = FakeEmbedder()
    store = InMemoryVectorStore(embedder)
    store.ingest(fact("tcad-1", "The home has three bedrooms and two bathrooms."))
    retriever = Retriever(store=store, embedder=embedder, min_score=0.1)
    evidence = retriever.retrieve("home has three bedrooms", address=ADDR)
    verdict = FakeEntailer().entail("home has three bedrooms", evidence)
    assert verdict.label is Label.ENTAILED
    assert verdict.score > 0.0
    assert verdict.source_id == "tcad-1"


def test_fake_entailer_opposite_polarity_is_contradicted():
    embedder = FakeEmbedder()
    store = InMemoryVectorStore(embedder)
    store.ingest(fact("tcad-2", "The home has no pool installed."))
    retriever = Retriever(store=store, embedder=embedder, min_score=0.1)
    evidence = retriever.retrieve("home has pool installed", address=ADDR)
    verdict = FakeEntailer().entail("home has pool installed", evidence)
    assert verdict.label is Label.CONTRADICTED


def test_fake_entailer_satisfies_entailer_protocol():
    assert isinstance(FakeEntailer(), Entailer)


def test_real_entailer_refuses_network_without_client_but_honors_no_source():
    real = RealEntailer()  # no client injected
    # build_request must only build a payload, never send.
    req = real.build_request("home has a pool", [])
    assert req["claim"] == "home has a pool"
    # empty evidence short-circuits to BASELESS without needing a client.
    assert real.entail("home has a pool", []).label is Label.BASELESS
    # with evidence but no client, it refuses rather than reaching the network.
    embedder = FakeEmbedder()
    store = InMemoryVectorStore(embedder)
    store.ingest(fact("tcad-3", "The home has a pool."))
    retriever = Retriever(store=store, embedder=embedder, min_score=0.1)
    evidence = retriever.retrieve("home has a pool", address=ADDR)
    with pytest.raises(RuntimeError):
        real.entail("home has a pool", evidence)


# --- AE1: Critic happy path — entailed claim passes WITH a citation ----------

def test_entailed_claim_passes_with_citation():
    critic = build_critic([fact("tcad-42", "The home has three bedrooms and two bathrooms.")])
    result = critic.verify("The home has three bedrooms.", address=ADDR)

    assert isinstance(result, VerificationResult)
    assert result.approved is True
    assert result.escalate is False
    assert result.confidence > 0.0
    # the surviving message is bound to a source citation.
    assert result.citations == ["tcad-42"]
    assert result.claims[0].supported is True
    assert result.claims[0].citation == "tcad-42"
    assert result.approved_message is not None


# --- AE1: unsupported claim is BLOCKED, not sent -----------------------------

def test_unsupported_claim_is_blocked_not_sent():
    # store has an unrelated fact, so "recently renovated" retrieves nothing.
    critic = build_critic([fact("tcad-7", "The lot is 8000 square feet.")])
    result = critic.verify("The home was recently renovated.", address=ADDR)

    assert result.approved is False
    assert result.escalate is True
    assert result.claims[0].label is Label.BASELESS
    assert result.claims[0].citation is None
    # nothing survives -> no approved message reaches output.
    assert result.approved_message is None
    assert "no source" in result.reason.lower()


# --- AE1: contradicted claim escalates ---------------------------------------

def test_contradicted_claim_escalates():
    critic = build_critic([fact("tcad-9", "The home has no pool installed.")])
    result = critic.verify("The home has a pool installed.", address=ADDR)

    assert result.approved is False
    assert result.escalate is True
    assert any(v.label is Label.CONTRADICTED for v in result.claims)
    assert "contradicted" in result.reason.lower()


def test_contradicted_via_fixture_escalates():
    # Pin a CONTRADICTED verdict explicitly via the entailer fixture.
    critic = build_critic(
        [fact("tcad-11", "The roof was replaced in 2019.")],
        fixtures={"the roof is brand new": Label.CONTRADICTED},
    )
    result = critic.verify("The roof is brand new.", address=ADDR)
    assert result.escalate is True
    assert result.approved is False


# --- AE1: partial support strips the unsupported claim, keeps the rest -------

def test_partial_support_strips_unsupported_keeps_supported():
    critic = build_critic(
        [fact("tcad-100", "The home has three bedrooms and two bathrooms.")]
    )
    # claim 1 is grounded (beds); claim 2 ("recently renovated") has no source.
    draft = "The home has three bedrooms. The home was recently renovated."
    result = critic.verify(draft, address=ADDR)

    labels = {v.claim: v.label for v in result.claims}
    supported = [v for v in result.claims if v.supported]
    stripped = [v for v in result.claims if not v.supported]

    assert len(supported) == 1
    assert len(stripped) == 1
    assert any("bedrooms" in v.claim for v in supported)
    assert any("renovated" in v.claim for v in stripped)
    # the rebuilt message keeps the supported claim, drops the unsupported one.
    assert "bedrooms" in result.approved_message
    assert "renovated" not in result.approved_message
    # whole draft still escalates because a claim was unsupported.
    assert result.approved is False
    assert result.escalate is True
    # the supported claim still carries its citation.
    assert supported[0].citation == "tcad-100"
    assert Label.ENTAILED in labels.values()
    assert Label.BASELESS in labels.values()


# --- AE1: per-claim source decisions are loggable (audit store) --------------

def test_result_carries_loggable_per_claim_source_decisions():
    critic = build_critic(
        [fact("tcad-200", "The home has three bedrooms and two bathrooms.")]
    )
    draft = "The home has three bedrooms. The home was recently renovated."
    result = critic.verify(draft, address=ADDR)

    rows = result.audit_rows()
    assert len(rows) == 2
    # every row is a flat dict ready for the U9 audit table.
    for row in rows:
        assert set(row) >= {
            "index", "claim", "label", "score", "citation", "supported", "reason",
        }
    by_claim = {row["claim"]: row for row in rows}
    bedrooms_row = next(r for c, r in by_claim.items() if "bedrooms" in c)
    renovated_row = next(r for c, r in by_claim.items() if "renovated" in c)
    assert bedrooms_row["citation"] == "tcad-200"
    assert bedrooms_row["supported"] is True
    assert renovated_row["citation"] is None
    assert renovated_row["supported"] is False


# --- composite-score gate ----------------------------------------------------

def test_low_composite_score_blocks_even_without_contradiction():
    # The claim entails (>= entail_threshold overlap) but not perfectly: only
    # some substantive tokens are covered, so its score sits below the high bar.
    critic = build_critic(
        [fact("tcad-300", "The home has three bedrooms.")],
        threshold=0.99,
    )
    result = critic.verify("The home has three updated bedrooms.", address=ADDR)
    # entailed + cited, but composite below the (artificially high) bar.
    assert result.claims[0].label is Label.ENTAILED
    assert 0.0 < result.confidence < 0.99
    assert result.approved is False
    assert result.escalate is True
    assert "threshold" in result.reason.lower()


def test_empty_draft_is_approved_with_no_claims():
    critic = build_critic([fact("tcad-1", "anything")])
    result = critic.verify("   ", address=ADDR)
    assert result.approved is True
    assert result.escalate is False
    assert result.claims == []


def test_critic_is_callable():
    critic = build_critic([fact("tcad-42", "The home has three bedrooms and two bathrooms.")])
    result = critic("The home has three bedrooms.", address=ADDR)
    assert result.approved is True
