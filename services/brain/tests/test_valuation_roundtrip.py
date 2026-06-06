"""U1 verification: the Brain gRPC service boots and answers a Valuation call.

This is the Python half of the cross-language contract test. The Go gateway
test (services/gateway/) exercises the same RPC from Go against a running brain.
"""
import grpc
import pytest

from genproto.realestate.v1 import realestate_pb2 as pb
from genproto.realestate.v1 import realestate_pb2_grpc as rpc
from brain.server import build_server


@pytest.fixture()
def brain_channel():
    server = build_server("localhost:0")
    # grpc picks a free port; recover it from the bound port.
    port = server.add_insecure_port("localhost:0")
    server.start()
    channel = grpc.insecure_channel(f"localhost:{port}")
    yield channel
    channel.close()
    server.stop(grace=None)


def test_valuation_returns_cited_estimate(brain_channel):
    client = rpc.ValuationStub(brain_channel)
    resp = client.GetValuation(pb.GetValuationRequest(address="123 Congress Ave, Austin TX"))
    assert resp.sufficient_data is True
    assert resp.estimate > 0
    assert resp.low <= resp.estimate <= resp.high
    assert len(resp.facts) >= 1  # every valuation carries a citable source fact


def test_empty_address_is_insufficient(brain_channel):
    client = rpc.ValuationStub(brain_channel)
    resp = client.GetValuation(pb.GetValuationRequest(address=""))
    assert resp.sufficient_data is False
    assert resp.estimate == 0


def test_getvaluation_real_features_path_anchors_on_comps():
    from genproto.realestate.v1 import realestate_pb2 as pb
    from brain.server import ValuationServicer

    req = pb.GetValuationRequest(
        address="9 Oak St, Austin, TX 78704",
        features=pb.PropertyFeatures(beds=4, baths=2, sqft=2000, year_built=2000,
                                     latitude=30.24, longitude=-97.77),
        comps=[pb.CompInput(id="a", price=400000, sqft=2000, age_days=5, address="1 A St")],
        as_of="2026-06-05T00:00:00Z",
        recent_activity="3 new listings in 30d",
    )
    resp = ValuationServicer().GetValuation(req, None)
    assert resp.sufficient_data is True
    assert resp.as_of == "2026-06-05T00:00:00Z"
    assert resp.recent_activity == "3 new listings in 30d"
    assert any(f.kind == "comp:active_listing" for f in resp.facts)
    # $400k comp anchor pulls the estimate well under the model's synthetic level.
    assert 350_000 < resp.estimate < 750_000


def test_getvaluation_address_only_still_works():
    from genproto.realestate.v1 import realestate_pb2 as pb
    from brain.server import ValuationServicer
    resp = ValuationServicer().GetValuation(pb.GetValuationRequest(address="5 Elm St"), None)
    assert resp.sufficient_data is True
    assert resp.as_of == ""  # no freshness on the hash-fallback path
