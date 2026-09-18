"""Local-only API for guided dashboard project setup."""

from uuid import UUID

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from dashboard.api.approvals import router as approvals_router
from dashboard.api.dashboard_specs import router as dashboard_specs_router
from dashboard.api.previews import router as previews_router
from dashboard.api.reports import router as reports_router
from dashboard.api.projects import project_repository, router as projects_router
from dashboard.api.revisions import router as revisions_router
from dashboard.api.schedules import schedule_runner, schedule_service
from dashboard.api.hermes import restore_active_api_provider, router as hermes_router
from dashboard.api.api_sources import router as api_sources_router
from dashboard.api.imports import router as imports_router
from dashboard.api.schedules import router as schedules_router
from dashboard.api.drift import router as drift_router
from dashboard.api.diagnostics import router as diagnostics_router
from dashboard.api.intake_workspace import router as intake_workspace_router
from dashboard.api.models import SetupCapabilities
from dashboard.api.uploads import UploadInspection, inspect_upload
from dashboard.api.security import enforce_local_security
from automation.agent.managed import managed_hermes
from automation.agent.oauth import codex_oauth
from automation.reports.service import artifact_store
from automation.pipeline import ProductionPipelineExecutor
from automation.agent.memory import MemoryKind, safe_memory_store


@asynccontextmanager
async def application_lifespan(_: FastAPI):
    artifact_store.start()
    restore_active_api_provider()
    managed_hermes.start()
    if schedule_runner.executor is None:
        schedule_runner.executor = ProductionPipelineExecutor()
    schedule_service.set_gateway_client(managed_hermes.client, script_directory=(managed_hermes.home / "scripts") if managed_hermes.home else None)
    schedule_service.start()
    try:
        yield
    finally:
        schedule_service.stop()
        codex_oauth.stop()
        managed_hermes.stop()
        artifact_store.stop()


app = FastAPI(
    title="Universal Dashboard Agent",
    version="0.2.1",
    description="Local API for creating and managing dashboard projects.",
    lifespan=application_lifespan,
)
app.include_router(approvals_router)
app.include_router(previews_router)
app.include_router(dashboard_specs_router)
app.include_router(reports_router)
app.include_router(projects_router)
app.include_router(revisions_router)
app.include_router(intake_workspace_router)

app.include_router(hermes_router)
app.include_router(api_sources_router)
app.include_router(imports_router)
app.include_router(schedules_router)
app.include_router(drift_router)
app.include_router(diagnostics_router)

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


@app.exception_handler(RequestValidationError)
async def request_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Return useful field errors without echoing rejected values."""

    fields = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ()) if part not in {"body", "query", "path"}) or "request",
            "message": str(error.get("msg", "Invalid value")),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"detail": {"code": "validation_error", "message": "Request validation failed", "fields": fields}},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/setup/capabilities", response_model=SetupCapabilities)
def setup_capabilities() -> SetupCapabilities:
    """Return only product capabilities confirmed in context.md."""
    return SetupCapabilities()


@app.get("/api/projects/{project_id}/memory")
def get_project_memory(project_id: UUID) -> list[dict[str, object]]:
    try:
        project_repository.get(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return safe_memory_store.project_context(str(project_id))


@app.delete("/api/projects/{project_id}/memory/{kind}/{key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project_memory(project_id: UUID, kind: MemoryKind, key: str) -> None:
    try:
        project_repository.get(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    if not safe_memory_store.forget(kind=MemoryKind(kind), key=key, project_id=str(project_id)):
        raise HTTPException(status_code=404, detail="Memory entry not found")


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
