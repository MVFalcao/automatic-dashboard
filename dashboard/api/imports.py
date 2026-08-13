"""Restart-safe, server-owned CSV/XLSX import review workflow."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from automation.discovery.models import Confidence, DraftDashboardSchema, FieldType, ProposedField, ProposedSection
from automation.importing import ImportApproval, ImportMode, ImportPlan, ImportResult, apply_import, inspect_data_location
from automation.persistence.workflow import ProjectWorkflowRepository, _atomic_json, canonical_checksum
from automation.specification.versioning import load_active_spec
from dashboard.api.projects import project_repository


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImportInspectRequest(StrictModel):
    project_id: UUID
    location: Path


class ImportInspectionRecord(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: UUID
    location: Path
    file_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    specification_version: int = Field(ge=1)
    plan_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan: ImportPlan
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ImportApprovalRequest(StrictModel):
    project_id: UUID
    inspection_id: str
    mode: ImportMode
    mappings: dict[str, str]
    relationships_confirmed: bool = False
    field_classifications: dict[str, bool]
    classification_overrides: dict[str, bool] = Field(default_factory=dict)
    update_identifier: str | None = None
    update_identifier_confirmed: bool = False
    permit_persistence: bool = False
    approved_by: str = Field(min_length=1, max_length=160)


class ImportApprovalRecord(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: UUID
    inspection_id: str
    file_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    plan_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: ImportApproval
    approved_by: str
    complete: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ImportApplyRequest(StrictModel):
    project_id: UUID
    inspection_id: str
    approval_id: str


def _files(location: Path) -> list[Path]:
    return sorted(path for path in location.iterdir() if path.is_file() and path.suffix.casefold() in {".csv", ".xlsx"}) if location.is_dir() else [location]


def _fingerprint(location: Path) -> str:
    digest = hashlib.sha256()
    for path in _files(location.resolve()):
        if not path.exists() or path.suffix.casefold() not in {".csv", ".xlsx"}:
            raise ValueError("Dashboard population supports local CSV and XLSX files only")
        digest.update(path.name.encode("utf-8"))
        digest.update(str(path.stat().st_size).encode("ascii"))
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def _draft_schema(project_directory: Path) -> DraftDashboardSchema:
    spec = load_active_spec(project_directory)
    type_map = {"text": FieldType.TEXT, "number": FieldType.NUMBER, "boolean": FieldType.BOOLEAN, "date": FieldType.DATE, "datetime": FieldType.DATETIME}
    return DraftDashboardSchema(
        source_format="approved-specification",
        fields=[ProposedField(id=field.id, display_name=field.label, inferred_type=type_map[field.kind.value], confidence=Confidence.HIGH, evidence=["Active approved specification"]) for field in spec.fields],
        sections=[ProposedSection(id=section.id, display_name=section.title, source_section=section.id, presentation=section.kind.value, confidence=Confidence.HIGH) for section in spec.sections],
        assumptions=[],
    )


def _repositories(project_id: UUID) -> tuple[object, ProjectWorkflowRepository]:
    try:
        project = project_repository.get(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    return project, ProjectWorkflowRepository(project.project_directory)


def _read_inspection(repository: ProjectWorkflowRepository, identifier: str) -> ImportInspectionRecord:
    return ImportInspectionRecord.model_validate(repository._read("import-inspections", identifier))


def _read_approval(repository: ProjectWorkflowRepository, identifier: str) -> ImportApprovalRecord:
    return ImportApprovalRecord.model_validate(repository._read("import-approvals", identifier))


router = APIRouter(prefix="/api/imports", tags=["imports"])


@router.post("/inspect", response_model=ImportInspectionRecord, status_code=201)
def inspect_import(payload: ImportInspectRequest) -> ImportInspectionRecord:
    project, repository = _repositories(payload.project_id)
    location = payload.location.expanduser().resolve()
    try:
        plan = inspect_data_location(location, _draft_schema(project.project_directory))
        fingerprint = _fingerprint(location)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if project.active_specification_version is None:
        raise HTTPException(status_code=409, detail="An active approved specification is required")
    record = ImportInspectionRecord(
        project_id=project.id, location=location, file_fingerprint=fingerprint,
        specification_version=project.active_specification_version,
        plan_checksum=canonical_checksum(plan), plan=plan,
    )
    _atomic_json(repository._path("import-inspections", record.id), record.model_dump(mode="json"))
    project_repository.save(project.model_copy(update={"inspection_ids": [*project.inspection_ids, record.id]}))
    return record


@router.post("/approve", response_model=ImportApprovalRecord, status_code=201)
def approve_import(payload: ImportApprovalRequest) -> ImportApprovalRecord:
    project, repository = _repositories(payload.project_id)
    try:
        inspection = _read_inspection(repository, payload.inspection_id)
        fingerprint = _fingerprint(inspection.location)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Import inspection not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if inspection.project_id != project.id or fingerprint != inspection.file_fingerprint:
        raise HTTPException(status_code=409, detail="The selected import files changed; re-inspection is required")
    detected = {column for source in inspection.plan.sources for column in source.likely_confidential_columns}
    decision = ImportApproval(
        approved=True, mode=payload.mode, mappings=payload.mappings,
        relationships_confirmed=payload.relationships_confirmed,
        confidential_columns=sorted(field for field, confidential in payload.field_classifications.items() if confidential),
        field_classifications=payload.field_classifications,
        classification_overrides=payload.classification_overrides,
        update_identifier=payload.update_identifier,
        update_identifier_confirmed=payload.update_identifier_confirmed,
        permit_persistence=payload.permit_persistence,
    )
    # Run validation before issuing the immutable approval.  The returned rows
    # exist only for this request and are immediately discarded.
    try:
        apply_import(inspection.location, inspection.plan, decision)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record = ImportApprovalRecord(
        project_id=project.id, inspection_id=inspection.id,
        file_fingerprint=inspection.file_fingerprint, plan_checksum=inspection.plan_checksum,
        decision=decision, approved_by=payload.approved_by,
    )
    _atomic_json(repository._path("import-approvals", record.id), record.model_dump(mode="json"))
    project_repository.save(project.model_copy(update={"approval_ids": [*project.approval_ids, record.id]}))
    return record


@router.post("/apply", response_model=ImportResult)
def apply_approved_import(payload: ImportApplyRequest) -> ImportResult:
    project, repository = _repositories(payload.project_id)
    try:
        inspection = _read_inspection(repository, payload.inspection_id)
        approval = _read_approval(repository, payload.approval_id)
        fingerprint = _fingerprint(inspection.location)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Import inspection or approval not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if inspection.project_id != project.id or approval.project_id != project.id or approval.inspection_id != inspection.id:
        raise HTTPException(status_code=409, detail="Import approval belongs to another workflow")
    if fingerprint != inspection.file_fingerprint or fingerprint != approval.file_fingerprint or canonical_checksum(inspection.plan) != approval.plan_checksum:
        raise HTTPException(status_code=409, detail="Import files or inspection changed; re-inspection is required")
    _, result = apply_import(inspection.location, inspection.plan, approval.decision)
    return result
