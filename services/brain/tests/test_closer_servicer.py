import grpc
import pytest

from genproto.realestate.v1 import realestate_pb2 as pb
from brain.closer_service import CloserServicer


class _Ctx:
    """Minimal gRPC context: abort records + raises (mirrors real abort)."""

    def __init__(self):
        self.code = None
        self.details = None

    def abort(self, code, details):
        self.code = code
        self.details = details
        raise RuntimeError("aborted")


def test_record_milestone_routes_earnest_to_escrow():
    resp = CloserServicer().RecordMilestone(
        pb.RecordMilestoneRequest(deal_id="deal-7", milestone="earnest_deposited"), _Ctx()
    )
    assert resp.pinged is True
    assert resp.counterparty == "escrow"
    assert "deal-7" in resp.message


def test_record_milestone_routes_funded_to_lender():
    resp = CloserServicer().RecordMilestone(
        pb.RecordMilestoneRequest(deal_id="deal-7", milestone="funded"), _Ctx()
    )
    assert resp.counterparty == "lender"


def test_record_milestone_rejects_unknown_milestone():
    ctx = _Ctx()
    with pytest.raises(RuntimeError):
        CloserServicer().RecordMilestone(
            pb.RecordMilestoneRequest(deal_id="deal-7", milestone="nope"), ctx
        )
    assert ctx.code == grpc.StatusCode.INVALID_ARGUMENT
