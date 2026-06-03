"""Tests for the Closer gRPC servicer (GenerateContract)."""
import json

from genproto.realestate.v1 import realestate_pb2 as pb

from brain.closer_service import CloserServicer


def _request(**overrides):
    base = dict(
        property_address="1900 Robert Browning St, Austin, TX 78757",
        buyer_name="Jordan Rivera",
        seller_name="Atlas Homes LLC",
        sales_price=615000.0,
        earnest_money=0.0,
        effective_date="2026-06-10",
        closing_date="2026-07-15",
        custom_clause_request="",
    )
    base.update(overrides)
    return pb.GenerateContractRequest(**base)


def test_generates_a_blanks_only_contract_draft():
    resp = CloserServicer().GenerateContract(_request(), None)

    assert resp.drafted is True
    assert resp.upl_blocked is False
    assert resp.status == "awaiting_broker"
    assert resp.form_id
    payload = json.loads(resp.form_json)
    # Factual blanks present...
    assert payload["blanks"]["property_address"].startswith("1900 Robert Browning")
    assert payload["blanks"]["sales_price"] == 615000.0
    # ...and structurally no free-text clause field (UPL boundary).
    assert "clause" not in payload
    assert "clauses" not in payload


def test_custom_clause_request_is_refused_as_handoff():
    resp = CloserServicer().GenerateContract(
        _request(custom_clause_request="add a personal indemnity clause for the buyer"), None
    )
    assert resp.drafted is False
    assert resp.upl_blocked is True
    assert "licensed broker" in resp.handoff_reason.lower()
    assert not resp.form_json


def test_invalid_facts_do_not_draft():
    resp = CloserServicer().GenerateContract(_request(sales_price=0.0), None)
    assert resp.drafted is False
    assert resp.upl_blocked is False
    assert resp.handoff_reason


def test_default_earnest_money_is_applied_when_zero():
    resp = CloserServicer().GenerateContract(_request(earnest_money=0.0), None)
    payload = json.loads(resp.form_json)
    # 1% default of 615000 = 6150.
    assert payload["blanks"]["earnest_money"] == 6150.0
