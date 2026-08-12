"""Local-only API for guided dashboard project setup."""

from uuid import UUID

import os

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from dashboard.api.approvals import router as approvals_router
from dashboard.api.dashboard_specs import router as dashboard_specs_router
from dashboard.api.previews import router as previews_router
from dashboard.api.reports import router as reports_router
from dashboard.api.projects import router as projects_router
from dashboard.api.hermes import router as hermes_router
from dashboard.api.api_sources import router as api_sources_router
from dashboard.api.schedules import router as schedules_router
from dashboard.api.drift import router as drift_router
from dashboard.api.intake import (
    IntakeAnswerRequest,
    IntakeResponse,
    StartIntakeRequest,
    intake_store,
)
from dashboard.api.models import SetupCapabilities
from dashboard.api.uploads import UploadInspection, inspect_upload
from dashboard.api.security import enforce_local_security


app = FastAPI(
    title="Universal Dashboard Agent",
    version="0.1.0",
    description="Local API for creating and managing dashboard projects.",
)
app.include_router(approvals_router)
app.include_router(previews_router)
app.include_router(dashboard_specs_router)
app.include_router(reports_router)
app.include_router(projects_router)
app.include_router(hermes_router)
app.include_router(api_sources_router)
app.include_router(schedules_router)
app.include_router(drift_router)

_origins = tuple(
    origin.strip().rstrip("/")
    for origin in os.environ.get("DASHBOARD_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
app.middleware("http")(enforce_local_security)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/setup/capabilities", response_model=SetupCapabilities)
def setup_capabilities() -> SetupCapabilities:
    """Return only product capabilities confirmed in context.md."""
    return SetupCapabilities()


@app.post("/api/intake", response_model=IntakeResponse, status_code=status.HTTP_201_CREATED)
def start_intake(payload: StartIntakeRequest) -> IntakeResponse:
    return intake_store.start(payload.language)


@app.post("/api/intake/{session_id}/answers", response_model=IntakeResponse)
def answer_intake(session_id: UUID, payload: IntakeAnswerRequest) -> IntakeResponse:
    try:
        return intake_store.answer(session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/api/intake/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_intake(session_id: UUID) -> None:
    try:
        intake_store.discard(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc


@app.post("/api/references/inspect", response_model=UploadInspection)
async def inspect_reference(
    file: UploadFile = File(...),
    confidential: bool = Form(...),
    permit_data_extraction: bool = Form(False),
) -> UploadInspection:
    try:
        return await inspect_upload(
            file,
            confidential=confidential,
            extracted_data_permitted=permit_data_extraction,
        )
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
