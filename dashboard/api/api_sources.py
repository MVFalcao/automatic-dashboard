"""Server-owned onboarding, approvals, and execution for JSON API sources."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from automation.agent.credentials import KeyringCredentialStore
from automation.connectors.client import ApiClient, ApiRequestError
from automation.connectors.models import ApiInspection, ApiSourceConfig, ApiSyncRequest, ApiSyncResult
from automation.persistence import ApiSourceApprovalRecord, ApiSourceInspectionRecord, ProjectWorkflowRepository
from automation.persistence.workflow import canonical_checksum
from dashboard.api.projects import project_repository
from automation.specification.versioning import load_active_spec


class ApiSourceSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    source: ApiSourceConfig


class ApiInspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID | None = None
    source_id: str | None = None
    # Kept only for value-free, non-persisted discovery compatibility.  It can
    # never be used by /sync and therefore cannot assert security state.
    source: ApiSourceConfig | None = None
    representative_json: Any | None = None
    openapi_document: dict[str, Any] | None = None
    target_fields: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_source_description(self) -> "ApiInspectRequest":
        if self.representative_json is None and self.openapi_document is None:
            raise ValueError("Provide representative JSON or an OpenAPI/Swagger document")
        if self.project_id is None or self.source_id is None:
            if self.source is None:
                raise ValueError("A project_id and source_id are required")
        elif self.source is not None:
            raise ValueError("Persisted inspection loads its source from the project")
        return self


class ApiApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    source_id: str
    inspection_id: str
    mappings: dict[str, str]
    field_classifications: dict[str, bool]
    approved_by: str = Field(min_length=1, max_length=160)


class ApiSyncEndpointRequest(BaseModel):
    """Only server-issued identifiers and execution options are accepted."""

    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    source_id: str
    inspection_id: str
    approval_id: str
    mode: str = Field(default="full", pattern=r"^(full|incremental)$")
    checkpoint: str | int | float | datetime | None = None


router = APIRouter(prefix="/api/api-sources", tags=["api-sources"])
try:
    _credential_store = KeyringCredentialStore()
except RuntimeError:
    _credential_store = None
_api_client = ApiClient(_credential_store)


def _repository(project_id: UUID) -> tuple[Any, ProjectWorkflowRepository]:
    try:
        project = project_repository.get(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return project, ProjectWorkflowRepository(project.project_directory)


@router.get("", response_model=list[ApiSourceConfig])
def list_api_sources(project_id: UUID) -> list[ApiSourceConfig]:
    _, repository = _repository(project_id)
    return repository.list_sources()


@router.put("/{source_id}", response_model=ApiSourceConfig)
def save_api_source(source_id: str, payload: ApiSourceSaveRequest) -> ApiSourceConfig:
    if payload.source.id != source_id:
        raise HTTPException(status_code=400, detail="Source id in the URL must match the configuration")
    project, repository = _repository(payload.project_id)
    repository.save_source(payload.source)
    if source_id not in project.source_ids:
        project_repository.save(project.model_copy(update={"source_ids": [*project.source_ids, source_id]}))
    return payload.source


@router.delete("/{source_id}", status_code=204)
def delete_api_source(source_id: str, project_id: UUID) -> None:
    project, repository = _repository(project_id)
    if source_id not in project.source_ids:
        raise HTTPException(status_code=404, detail="API source not found")
    # Source deletion is metadata-only and is intentionally explicit.  Old
    # immutable inspections/approvals remain as an audit trail.
    repository._path("sources", source_id).unlink(missing_ok=True)
    project_repository.save(project.model_copy(update={"source_ids": [item for item in project.source_ids if item != source_id]}))


@router.post("/inspect")
def inspect_api_source(payload: ApiInspectRequest) -> ApiInspection | ApiSourceInspectionRecord:
    if payload.project_id is None or payload.source_id is None:
        assert payload.source is not None
        return _api_client.inspect(
            payload.source, payload.representative_json,
            target_fields=payload.target_fields, openapi_document=payload.openapi_document,
        )
    project, repository = _repository(payload.project_id)
    try:
        source = repository.get_source(payload.source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="API source not found") from exc
    inspection = _api_client.inspect(
        source, payload.representative_json,
        target_fields=payload.target_fields, openapi_document=payload.openapi_document,
    )
    record = ApiSourceInspectionRecord(
        project_id=project.id,
        source_id=source.id,
        source_checksum=canonical_checksum(source),
        inspection_checksum=canonical_checksum(inspection),
        inspection=inspection,
    )
    repository.save_inspection(record)
    project_repository.save(project.model_copy(update={"inspection_ids": [*project.inspection_ids, record.id]}))
    return record


@router.post("/approve", response_model=ApiSourceApprovalRecord, status_code=201)
def approve_api_source(payload: ApiApprovalRequest) -> ApiSourceApprovalRecord:
    project, repository = _repository(payload.project_id)
    try:
        source = repository.get_source(payload.source_id)
        inspection = repository.get_inspection(payload.inspection_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Source inspection not found") from exc
    if inspection.project_id != project.id or inspection.source_id != source.id:
        raise HTTPException(status_code=409, detail="Inspection belongs to another project or source")
    if canonical_checksum(source) != inspection.source_checksum:
        raise HTTPException(status_code=409, detail="The source changed; re-inspection is required")
    fields = {field.path for field in inspection.inspection.fields}
    if set(payload.field_classifications) != fields:
        raise HTTPException(status_code=409, detail="Every inspected field requires a confidentiality classification")
    if not payload.mappings or set(payload.mappings) - fields:
        raise HTTPException(status_code=409, detail="Mappings must come from the immutable inspection")
    try:
        active_specification = load_active_spec(project.project_directory)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="An active approved specification is required") from exc
    target_fields = {field.id for field in active_specification.fields}
    if set(payload.mappings.values()) - target_fields:
        raise HTTPException(status_code=409, detail="Mappings must target fields in the active approved specification")
    record = ApiSourceApprovalRecord(
        project_id=project.id, source_id=source.id, inspection_id=inspection.id,
        source_checksum=inspection.source_checksum, inspection_checksum=inspection.inspection_checksum,
        mappings=payload.mappings, field_classifications=payload.field_classifications,
        approved_by=payload.approved_by,
    )
    repository.save_approval(record)
    project_repository.save(project.model_copy(update={
        "approval_ids": [*project.approval_ids, record.id],
        "active_source_id": source.id,
        "active_source_inspection_id": inspection.id,
        "active_source_approval_id": record.id,
    }))
    return record


@router.post("/sync", response_model=ApiSyncResult)
def sync_api_source(payload: ApiSyncEndpointRequest) -> ApiSyncResult:
    project, repository = _repository(payload.project_id)
    try:
        source, inspection, approval = repository.verify(
            project.id, payload.source_id, payload.inspection_id, payload.approval_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Source inspection or approval not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    request = ApiSyncRequest(
        source=source, mode=payload.mode,
        checkpoint=payload.checkpoint if payload.checkpoint is not None else project.checkpoints.get(source.id),
        approved_mappings=approval.mappings, approval_confirmed=True,
        inspection_version=inspection.inspection_checksum,
    )
    try:
        return _api_client.sync(request, expected_inspection=inspection.inspection)
    except ApiRequestError as exc:
        code = 409 if "drift" in str(exc).casefold() or "approval" in str(exc).casefold() else 502
        raise HTTPException(status_code=code, detail=str(exc)) from exc
