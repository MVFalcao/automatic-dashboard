"""Local API routes for section-level schema approval."""

from uuid import UUID

from fastapi import APIRouter, HTTPException

from automation.approval.models import (
    ApprovalPackage,
    CreateApprovalRequest,
    SectionDecisionRequest,
)
from automation.approval.service import approval_store


router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.post("", response_model=ApprovalPackage, status_code=201)
def create_approval(payload: CreateApprovalRequest) -> ApprovalPackage:
    try:
        return approval_store.create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{approval_id}", response_model=ApprovalPackage)
def get_approval(approval_id: UUID) -> ApprovalPackage:
    try:
        return approval_store.get(approval_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval package not found") from exc


@router.post("/{approval_id}/sections/{section_id}", response_model=ApprovalPackage)
def decide_section(
    approval_id: UUID,
    section_id: str,
    payload: SectionDecisionRequest,
) -> ApprovalPackage:
    try:
        return approval_store.decide(
            approval_id,
            section_id,
            approve=payload.approve,
            feedback=payload.feedback,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval package not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
