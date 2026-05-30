"""Brain gRPC server.

Serves Valuation and Verification. U1 wires the Valuation servicer to the
placeholder core and a permissive Verification stub so the service boots and the
gateway round-trip works. U3/U6 replace the servicer bodies with the real AVM
and the decompose -> retrieve -> entail -> cite -> score Critic pipeline.
"""
from __future__ import annotations

import os
from concurrent import futures

import grpc

from genproto.realestate.v1 import realestate_pb2 as pb
from genproto.realestate.v1 import realestate_pb2_grpc as rpc

from brain.valuation import estimate_value


class ValuationServicer(rpc.ValuationServicer):
    def GetValuation(self, request, context):
        v = estimate_value(request.address)
        return pb.GetValuationResponse(
            sufficient_data=v.sufficient_data,
            estimate=v.estimate,
            low=v.low,
            high=v.high,
            facts=[
                pb.SourceFact(
                    source_id=f.source_id,
                    kind=f.kind,
                    description=f.description,
                    contribution=f.contribution,
                )
                for f in v.facts
            ],
        )


class VerificationServicer(rpc.VerificationServicer):
    """U1 stub: approves with low confidence so nothing ships unverified by
    accident downstream. U6 replaces this with the real Critic pipeline."""

    def VerifyMessage(self, request, context):
        return pb.VerifyMessageResponse(
            approved=False,
            escalate=True,
            confidence=0.0,
            reason="U1 stub: Critic not yet implemented (U6).",
        )


def build_server(address: str) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    rpc.add_ValuationServicer_to_server(ValuationServicer(), server)
    rpc.add_VerificationServicer_to_server(VerificationServicer(), server)
    server.add_insecure_port(address)
    return server


def main() -> None:
    address = os.environ.get("BRAIN_BIND", "[::]:50051")
    # Warm the AVM (trains the gradient-boosting model once) before serving so
    # the first GetValuation call isn't slow enough to trip client timeouts.
    estimate_value("warmup")
    server = build_server(address)
    server.start()
    print(f"brain listening on {address}", flush=True)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
