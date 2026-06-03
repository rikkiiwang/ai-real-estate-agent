"""Closer gRPC servicer — makes the TREC paperwork reachable.

Wraps the existing, fully-tested :func:`brain.lawyer.trec_form.fill_trec_form`
behind the ``Closer.GenerateContract`` RPC so the Rails consumer marketplace can
produce a promulgated-form contract draft on offer acceptance. No new business
logic: the UPL boundary (blanks only, custom clauses refused) and the
"awaiting-broker, never signed" property hold by construction in the reused
form-fill machinery.
"""
from __future__ import annotations

import json
import logging

from genproto.realestate.v1 import realestate_pb2 as pb
from genproto.realestate.v1 import realestate_pb2_grpc as rpc

from brain.lawyer.trec_form import TrecTerms, UplViolation, fill_trec_form
from brain.orchestrator.closer import DEFAULT_EARNEST_MONEY_RATE

logger = logging.getLogger(__name__)


class CloserServicer(rpc.CloserServicer):
    """Implements Closer.GenerateContract by filling a promulgated TREC form."""

    def GenerateContract(self, request, context):  # noqa: N802 (gRPC naming)
        earnest = request.earnest_money or round(request.sales_price * DEFAULT_EARNEST_MONEY_RATE, 2)
        custom = request.custom_clause_request.strip() if request.custom_clause_request else None

        terms = TrecTerms(
            seller_name=request.seller_name,
            buyer_name=request.buyer_name,
            property_address=request.property_address,
            sales_price=request.sales_price,
            earnest_money=earnest,
            effective_date=request.effective_date,
            closing_date=request.closing_date,
            custom_clause_request=custom,
        )

        try:
            form = fill_trec_form(terms)
        except UplViolation as exc:
            # A non-standard clause was requested — refuse and escalate (never
            # author clause language). This is the UPL line, surfaced as handoff.
            return pb.GenerateContractResponse(
                drafted=False,
                upl_blocked=True,
                handoff_reason=(
                    "A custom contract clause was requested — that needs a "
                    f"licensed broker/attorney, not the agent: {exc}"
                ),
            )
        except ValueError as exc:
            # Missing/invalid factual blanks — cannot draft.
            return pb.GenerateContractResponse(
                drafted=False,
                upl_blocked=False,
                handoff_reason=f"Cannot draft yet: {exc}",
            )

        return pb.GenerateContractResponse(
            drafted=True,
            form_id=form.form_id,
            title=form.title,
            form_json=json.dumps(form.to_dict()),
            status="awaiting_broker",
        )
