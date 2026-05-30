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
