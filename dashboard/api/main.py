"""Local-only API for guided dashboard project setup."""

from uuid import UUID

import os
import json
import httpx
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from fastapi.middleware.cors import CORSMiddleware

from dashboard.api.approvals import router as approvals_router
from dashboard.api.dashboard_specs import router as dashboard_specs_router
from dashboard.api.previews import router as previews_router
from dashboard.api.reports import router as reports_router
from dashboard.api.projects import project_repository, router as projects_router
from dashboard.api.schedules import schedule_runner, schedule_service
from dashboard.api.hermes import restore_active_api_provider, router as hermes_router
from dashboard.api.api_sources import router as api_sources_router
from dashboard.api.imports import router as imports_router
from dashboard.api.schedules import router as schedules_router
from dashboard.api.drift import router as drift_router
from dashboard.api.diagnostics import router as diagnostics_router
from dashboard.api.intake import (
    IntakeAnswerRequest,
    IntakeResponse,
    StartIntakeRequest,
    intake_store,
)
from dashboard.api.models import SetupCapabilities
from dashboard.api.uploads import UploadInspection, inspect_upload
from dashboard.api.security import enforce_local_security
from automation.agent.managed import managed_hermes
from automation.agent.oauth import codex_oauth
from automation.reports.service import artifact_store
from automation.pipeline import ProductionPipelineExecutor
from automation.approval.models import ApprovalPackage, CreateApprovalRequest
from automation.approval.service import approval_store
from automation.discovery.models import Confidence, DraftDashboardSchema, FieldType, ProposedField, ProposedSection
from automation.reports import ReportDocument, build_report_document
from automation.specification.models import (
    DashboardSpec, FieldDefinition, FieldKind, FieldMapping, LayoutSpec,
    LocalizationSpec, MetricDefinition, OutputKind, OutputSpec, PrivacyPolicy,
    SectionKind, SectionSpec, VisualizationKind, VisualizationSpec,
    StyleSpec,
)
from automation.agent.memory import MemoryKind, SafeMemoryStore
from automation.release.support import support_events


class IntakeWorkspacePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: ReportDocument
    approval: ApprovalPackage
    project_id: UUID | None = None


class IntakeProjectLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID


class PreviewDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accent_color: str = Field(default="#1D4ED8", pattern=r"^#[0-9a-fA-F]{6}$")
    chart_type: str = Field(default="bar", pattern=r"^(bar|line|pie)$")
    section_order: list[str] = Field(min_length=1)
    terminology: dict[str, str] = Field(default_factory=dict)
    feedback: str | None = None
    feedback_non_confidential: bool = False


class PreviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    status: str = "draft"
    accent_color: str
    chart_type: str
    section_order: list[str]
    terminology: dict[str, str]
    feedback_applied_by_hermes: bool = False


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


@app.get("/api/intake/{session_id}", response_model=IntakeResponse)
def reopen_intake(session_id: UUID) -> IntakeResponse:
    try:
        return intake_store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc


@app.get("/api/intake/{session_id}/preview", response_model=IntakeWorkspacePreview)
def intake_preview(session_id: UUID) -> IntakeWorkspacePreview:
    try:
        response = intake_store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc
    if response.step.value != "complete":
        raise HTTPException(status_code=409, detail="Complete intake before generating a preview")
    language = response.language.value
    title = response.confirmed_context.get("goal", "Dashboard")[:120]
    saved_draft = intake_store.get_resource(session_id, "_draft")
    draft_options = PreviewDraft.model_validate_json(saved_draft) if saved_draft else None
    terminology = draft_options.terminology if draft_options else {}
    requested_outputs = response.confirmed_context.get("outputs", "web").casefold()
    enabled_outputs = [
        output for marker, output in (("web", OutputKind.WEB), ("excel", OutputKind.EXCEL), ("xlsx", OutputKind.EXCEL), ("pdf", OutputKind.PDF))
        if marker in requested_outputs
    ]
    enabled_outputs = list(dict.fromkeys(enabled_outputs)) or [OutputKind.WEB]
    fields = [
        FieldDefinition(id="group", label=terminology.get("group", "Grupo" if language == "pt" else "Group"), kind=FieldKind.TEXT),
        FieldDefinition(id="value", label=terminology.get("value", "Valor" if language == "pt" else "Value"), kind=FieldKind.NUMBER),
    ]
    section_order = draft_options.section_order if draft_options else ["summary", "distribution", "details"]
    order_index = {identifier: index for index, identifier in enumerate(section_order)}
    spec = DashboardSpec(
        id=f"intake-{session_id}", title=title, fields=fields,
        mappings=[FieldMapping(source_field=item.id, target_field=item.id, approved=True) for item in fields],
        metrics=[
            MetricDefinition(id="records", label="Registros" if language == "pt" else "Records", operation="count", explanation="Contagem de registros." if language == "pt" else "Count of records.", approved=True),
            MetricDefinition(id="total", label="Total", operation="sum", field="value", explanation="Soma determinística dos valores." if language == "pt" else "Deterministic sum of values.", approved=True),
        ],
        visualizations=[VisualizationSpec(id="distribution", kind=VisualizationKind(draft_options.chart_type if draft_options else "bar"), title="Distribuição" if language == "pt" else "Distribution", dimension_field="group", value_field="value")],
        sections=[
            SectionSpec(id="summary", title="Resumo" if language == "pt" else "Summary", kind=SectionKind.METRICS, metric_ids=["records", "total"], order=order_index["summary"]),
            SectionSpec(id="distribution", title="Distribuição" if language == "pt" else "Distribution", kind=SectionKind.CHART, visualization_ids=["distribution"], depends_on=["summary"], order=order_index["distribution"]),
            SectionSpec(id="details", title="Detalhes" if language == "pt" else "Details", kind=SectionKind.TABLE, field_ids=["group", "value"], depends_on=["summary"], order=order_index["details"]),
        ],
        layout=LayoutSpec(), localization=LocalizationSpec(language=language, locale="pt-BR" if language == "pt" else "en-US", timezone="America/Sao_Paulo" if language == "pt" else "UTC"),
        privacy=PrivacyPolicy(), outputs=OutputSpec(enabled=enabled_outputs),
        terminology=terminology,
        style=StyleSpec(palette=[draft_options.accent_color if draft_options else "#1D4ED8"]),
    )
    records = [{"group": f"{fields[0].label} {((index - 1) % 5) + 1}", "value": 100 + ((index * 173) % 900)} for index in range(1, 19)]
    document = build_report_document(spec, records, synthetic=True)
    draft = DraftDashboardSchema(
        source_format="guided-intake",
        fields=[ProposedField(id=item.id, display_name=item.label, inferred_type=FieldType.NUMBER if item.kind is FieldKind.NUMBER else FieldType.TEXT, confidence=Confidence.MEDIUM, evidence=["Guided intake synthetic preview"]) for item in fields],
        sections=[ProposedSection(id=item.id, display_name=item.title, source_section="guided-intake", presentation=item.kind.value, confidence=Confidence.MEDIUM) for item in spec.sections],
        assumptions=["This structure uses synthetic data and remains a draft until every section is approved."],
    )
    stored = intake_store.get_resource(session_id, "_approval_id")
    try:
        approval = approval_store.get(UUID(stored)) if stored else None
    except (KeyError, ValueError):
        approval = None
    if approval is None:
        approval = approval_store.create(CreateApprovalRequest(draft_schema=draft, dependencies={"distribution": ["summary"], "details": ["summary"]}))
        intake_store.set_resource(session_id, "_approval_id", str(approval.approval_id))
    linked_project = intake_store.get_resource(session_id, "_project_id")
    return IntakeWorkspacePreview(
        document=document,
        approval=approval,
        project_id=UUID(linked_project) if linked_project else None,
    )


@app.post("/api/intake/{session_id}/project-link", status_code=204)
def link_intake_project(session_id: UUID, payload: IntakeProjectLinkRequest) -> None:
    try:
        project_repository.get(payload.project_id)
        intake_store.set_resource(session_id, "_project_id", str(payload.project_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session or project not found") from exc


@app.get("/api/intake/{session_id}/draft", response_model=PreviewDraft | None)
def get_intake_draft(session_id: UUID):
    try:
        raw = intake_store.get_resource(session_id, "_draft")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc
    return PreviewDraft.model_validate_json(raw) if raw else None


@app.post("/api/intake/{session_id}/draft", response_model=PreviewDraft, status_code=201)
def create_intake_draft(session_id: UUID, payload: PreviewDraftRequest) -> PreviewDraft:
    try:
        intake_store.get(session_id)
        previous = intake_store.get_resource(session_id, "_draft")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc
    if payload.feedback:
        if not payload.feedback_non_confidential:
            raise HTTPException(status_code=409, detail="Confirm the feedback is non-confidential before sending it to Hermes")
        try:
            SafeMemoryStore().remember(kind=MemoryKind.FEEDBACK, key="preview_feedback", value=payload.feedback)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Feedback appears confidential and was not sent to Hermes") from exc
        from dashboard.api.hermes import provider_registry
        from automation.agent.models import ProviderName

        codex = provider_registry.get(ProviderName.CODEX)
        if codex is not None and (not codex.connected or codex.model != "gpt-5.5"):
            raise HTTPException(status_code=409, detail={
                "code": "provider_model_incompatible",
                "message": "The connected Codex provider is not ready for gpt-5.5. Reconnect Codex before retrying.",
                "fields": [{"field": "provider", "message": "Expected openai-codex with gpt-5.5."}],
            })
        client = managed_hermes.client
        if client is None:
            raise HTTPException(status_code=503, detail={
                "code": "provider_not_ready",
                "message": "Hermes is not ready. Connect an AI provider and try again.",
                "fields": [{"field": "provider", "message": "Choose a provider and connect its API key."}],
            })
        allowed_sections = {"summary", "distribution", "details"}
        for attempt in range(2):
            try:
                try:
                    raw = client.chat(
                        model="hermes-agent",
                        messages=[{"role": "user", "content": json.dumps({
                            "instruction": "Return one strict JSON object with accent_color, chart_type, section_order, and terminology only. Include every section exactly once.",
                            "feedback": payload.feedback,
                            "current": payload.model_dump(exclude={"feedback"}),
                            "required_sections": sorted(allowed_sections),
                            "repair_attempt": attempt == 1,
                        }, ensure_ascii=False)}],
                        response_format={"type": "json_object"},
                    )
                except httpx.HTTPError as exc:
                    support_events.record("hermes_provider_unavailable", level="WARNING", details={"code": "provider_unavailable", "component": "review"})
                    raise HTTPException(status_code=503, detail={
                        "code": "provider_unavailable",
                        "message": "No working AI provider is available. Connect a provider in this review screen and try again.",
                        "fields": [{"field": "provider", "message": "Check the API key, provider access, and network connection."}],
                    }) from exc
                content = raw["choices"][0]["message"]["content"]
                proposed = PreviewDraftRequest.model_validate_json(content).model_copy(update={"feedback": None, "feedback_non_confidential": False})
                if set(proposed.section_order) != allowed_sections or len(proposed.section_order) != len(allowed_sections):
                    raise ValueError("Invalid reviewed section order")
                payload = proposed
                hermes_applied = True
                break
            except HTTPException:
                # Provider/runtime failures already carry actionable status and
                # must not be mistaken for repairable structured JSON.
                raise
            except Exception as exc:
                if attempt == 1:
                    support_events.record("hermes_draft_invalid", level="WARNING", details={"attempt": 2, "code": "invalid_hermes_draft", "component": "review"})
                    raise HTTPException(status_code=422, detail={
                        "code": "invalid_hermes_draft",
                        "message": "Hermes could not produce a valid dashboard revision after one retry. The active specification was not changed.",
                        "fields": [{"field": "feedback", "message": "Revise the request and try again."}],
                    }) from exc
    else:
        hermes_applied = False
    allowed_sections = {"summary", "distribution", "details"}
    if set(payload.section_order) != allowed_sections or len(payload.section_order) != len(allowed_sections):
        raise HTTPException(status_code=409, detail="Draft section order must contain every reviewed section exactly once")
    safe_memory = SafeMemoryStore()
    try:
        for key, value in payload.terminology.items():
            safe_memory.remember(kind=MemoryKind.PROJECT_TERMINOLOGY, key=key, value=value)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Draft terminology appears confidential and was not persisted") from exc
    version = PreviewDraft.model_validate_json(previous).version + 1 if previous else 1
    draft = PreviewDraft(
        version=version, accent_color=payload.accent_color, chart_type=payload.chart_type,
        section_order=payload.section_order, terminology=payload.terminology,
        feedback_applied_by_hermes=hermes_applied,
    )
    intake_store.set_resource(session_id, "_draft", draft.model_dump_json())
    # Any structural/design change starts a fresh review package.  The active
    # approved project specification, if one exists, remains untouched.
    intake_store.set_resource(session_id, "_approval_id", "")
    return draft


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
