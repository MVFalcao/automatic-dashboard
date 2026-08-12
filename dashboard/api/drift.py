"""Schema-drift endpoint: classify changes and create approval drafts."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from automation.connectors.models import ApiInspection, SchemaDriftEvent
from automation.drift.classifier import classify_schema_drift
from automation.drift.models import DriftDraft
from automation.drift.service import DriftDraftStore, create_draft
from automation.specification.models import DashboardSpec


class DriftCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected: ApiInspection
    actual: ApiInspection


class DriftDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specification: DashboardSpec
    events: list[SchemaDriftEvent] = Field(min_length=1)
    proposed: DashboardSpec | None = None
    base_version: int | None = Field(default=None, ge=1)
    record_count: int = Field(default=24, ge=1, le=500)


router = APIRouter(prefix="/api/drift", tags=["drift"])
drift_draft_store = DriftDraftStore()


@router.post("/classify", response_model=list[SchemaDriftEvent])
def classify(payload: DriftCompareRequest) -> list[SchemaDriftEvent]:
    return classify_schema_drift(payload.expected, payload.actual)


@router.post("/drafts", response_model=DriftDraft, status_code=201)
def create_drift_draft(payload: DriftDraftRequest) -> DriftDraft:
    try:
        return drift_draft_store.create(create_draft(
            payload.specification,
            payload.events,
            proposed=payload.proposed,
            base_version=payload.base_version,
            record_count=payload.record_count,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/drafts", response_model=list[DriftDraft])
def list_drift_drafts(specification_id: str | None = None) -> list[DriftDraft]:
    return drift_draft_store.list(specification_id=specification_id)


@router.get("/drafts/{draft_id}", response_model=DriftDraft)
def get_drift_draft(draft_id: str) -> DriftDraft:
    try:
        return drift_draft_store.get(draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Drift draft not found") from exc
