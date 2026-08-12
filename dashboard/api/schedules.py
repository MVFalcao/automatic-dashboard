"""Local schedule management, previews, runs, and artifact history."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from automation.scheduling.cron import CronError, preview_schedule
from automation.scheduling.models import ArtifactRecord, RunRecord, ScheduleDefinition
from automation.observability.models import AuditEvent
from automation.scheduling.runner import LocalPipelineRunner, PipelineExecutor
from automation.scheduling.store import ScheduleStore
from automation.scheduling.service import LocalSchedulerService


def _default_database() -> Path:
    configured = os.environ.get("DASHBOARD_SCHEDULER_DB")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "universal-dashboard-agent" / "schedules.sqlite3"


schedule_store = ScheduleStore(_default_database())
schedule_runner = LocalPipelineRunner(schedule_store)
schedule_service = LocalSchedulerService(schedule_store, schedule_runner)


class SchedulePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule: ScheduleDefinition
    after: datetime | None = None
    count: int = Field(default=5, ge=1, le=100)


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_for: datetime | None = None


class ActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved_by: str = Field(min_length=1, max_length=160)


router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def configure_scheduler(*, executor: PipelineExecutor | None = None, runner: LocalPipelineRunner | None = None) -> None:
    """Configure the process-local runner (used by the application and tests)."""

    global schedule_runner
    if runner is not None:
        schedule_runner = runner
    else:
        schedule_runner = LocalPipelineRunner(schedule_store, executor=executor)
    global schedule_service
    schedule_service = LocalSchedulerService(schedule_store, schedule_runner)


@router.post("/preview")
def preview_schedule_endpoint(payload: SchedulePreviewRequest) -> dict[str, str | list[str]]:
    try:
        occurrences = preview_schedule(
            payload.schedule,
            after=payload.after or datetime.now(timezone.utc),
            count=payload.count,
        )
    except CronError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"timezone": payload.schedule.timezone, "occurrences": [item.isoformat() for item in occurrences]}


@router.get("", response_model=list[ScheduleDefinition])
def list_schedules(project_id: str | None = None) -> list[ScheduleDefinition]:
    return schedule_store.list_schedules(project_id=project_id)


@router.post("", response_model=ScheduleDefinition, status_code=201)
def create_schedule(payload: ScheduleDefinition) -> ScheduleDefinition:
    try:
        return schedule_store.create_schedule(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{schedule_id}", response_model=ScheduleDefinition)
def get_schedule(schedule_id: str) -> ScheduleDefinition:
    try:
        return schedule_store.get_schedule(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc


@router.put("/{schedule_id}", response_model=ScheduleDefinition)
def update_schedule(schedule_id: str, payload: ScheduleDefinition) -> ScheduleDefinition:
    if payload.id != schedule_id:
        raise HTTPException(status_code=400, detail="Schedule id in the URL must match the definition")
    try:
        return schedule_store.update_schedule(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{schedule_id}/activate", response_model=ScheduleDefinition)
def activate_schedule(schedule_id: str, payload: ActivationRequest) -> ScheduleDefinition:
    try:
        schedule = schedule_store.get_schedule(schedule_id)
        schedule = schedule.model_copy(update={"enabled": True, "approval_confirmed": True, "approved_by": payload.approved_by})
        return schedule_store.update_schedule(schedule)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{schedule_id}/deactivate", response_model=ScheduleDefinition)
def deactivate_schedule(schedule_id: str) -> ScheduleDefinition:
    try:
        schedule = schedule_store.get_schedule(schedule_id)
        return schedule_store.update_schedule(schedule.model_copy(update={"enabled": False}))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: str) -> None:
    try:
        schedule_store.delete_schedule(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc


@router.post("/{schedule_id}/run", response_model=RunRecord)
def run_schedule(schedule_id: str, payload: RunRequest | None = None) -> RunRecord:
    try:
        return schedule_runner.run(schedule_id, scheduled_for=payload.scheduled_for if payload else None)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{schedule_id}/runs", response_model=list[RunRecord])
def list_schedule_runs(schedule_id: str, limit: int = 100) -> list[RunRecord]:
    try:
        schedule_store.get_schedule(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    return schedule_store.list_runs(schedule_id=schedule_id, limit=limit)


@router.get("/{schedule_id}/artifacts", response_model=list[ArtifactRecord])
def list_schedule_artifacts(schedule_id: str) -> list[ArtifactRecord]:
    try:
        schedule_store.get_schedule(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    return schedule_store.list_artifacts(schedule_id=schedule_id)


@router.get("/{schedule_id}/audit", response_model=list[AuditEvent])
def list_schedule_audit(schedule_id: str, limit: int = 100) -> list[AuditEvent]:
    try:
        schedule_store.get_schedule(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Schedule not found") from exc
    return schedule_store.list_audit(project_id=schedule_store.get_schedule(schedule_id).project_id, limit=limit)
