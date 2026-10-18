"""Reviewer-only HTTP boundary for resolution operations."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.reviewer_auth import reviewer_identity
from app.db.session import SessionLocal
from app.models.entities import DisputeCase
from app.models.resolutions import CaseReview
from app.repositories.resolutions import list_cases, list_events
from app.schemas.resolutions import ReviewRequest
from app.services.case_similarity import similar_resolutions
from app.services.disputes import serialize_case
from app.services.resolutions import ResolutionError, execute_refund, review_case

router = APIRouter(prefix="/reviewer/cases", tags=["reviewer"])


@router.get("")
async def case_queue(
    status: Literal["awaiting_review", "awaiting_investigation", "approved", "rejected", "resolved"]
    | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    reviewer=Depends(reviewer_identity),
):
    async with SessionLocal() as db:
        cases, has_more = await list_cases(db, status, limit, offset)
        return {
            "items": [
                {
                    "id": case.id,
                    "order_id": case.order_id,
                    "customer_id": case.customer_id,
                    "status": case.status,
                    "created_at": case.created_at.isoformat(),
                }
                for case in cases
            ],
            "has_more": has_more,
        }


@router.get("/{case_id}")
async def case_detail(case_id: str, reviewer=Depends(reviewer_identity)):
    async with SessionLocal() as db:
        case = await db.get(DisputeCase, case_id)
        if case is None:
            raise HTTPException(404, "Case not found")
        review = await db.get(CaseReview, case_id)
        return {
            **serialize_case(case),
            "customer_id": case.customer_id,
            "review": None
            if review is None
            else {
                "reviewer_id": review.reviewer_id,
                "decision": review.decision,
                "reason": review.reason,
                "amount_cents": review.amount_cents,
                "created_at": review.created_at.isoformat(),
            },
        }


async def run_operation(operation, *args):
    try:
        async with SessionLocal() as db:
            return await operation(db, *args)
    except ResolutionError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("/{case_id}/review")
async def review(case_id: str, body: ReviewRequest, reviewer=Depends(reviewer_identity)):
    return await run_operation(review_case, case_id, reviewer, body)


@router.get("/{case_id}/similar")
async def similar_cases(
    case_id: str, limit: int = Query(default=3, ge=1, le=10), reviewer=Depends(reviewer_identity)
):
    async with SessionLocal() as db:
        case = await db.get(DisputeCase, case_id)
        if case is None:
            raise HTTPException(404, "Case not found")
        return await similar_resolutions(db, case, limit)


@router.post("/{case_id}/execute")
async def execute(case_id: str, reviewer=Depends(reviewer_identity)):
    return await run_operation(execute_refund, case_id, reviewer)


@router.get("/{case_id}/audit")
async def audit(case_id: str, reviewer=Depends(reviewer_identity)):
    async with SessionLocal() as db:
        if await db.get(DisputeCase, case_id) is None:
            raise HTTPException(404, "Case not found")
        return {"case_id": case_id, "events": await list_events(db, case_id)}
