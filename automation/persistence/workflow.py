"""Immutable inspection and approval records stored inside a project folder."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from automation.connectors.models import ApiInspection, ApiSourceConfig


def canonical_checksum(value: BaseModel | dict) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiSourceInspectionRecord(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: UUID
    source_id: str
    source_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    inspection_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    inspection: ApiInspection
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApiSourceApprovalRecord(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: UUID
    source_id: str
    inspection_id: str
    source_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    inspection_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    mappings: dict[str, str]
    field_classifications: dict[str, bool]
    approved_by: str = Field(min_length=1, max_length=160)
    complete: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def complete_decisions(self) -> "ApiSourceApprovalRecord":
        if not self.mappings:
            raise ValueError("At least one source mapping must be approved")
        return self


class ProjectWorkflowRepository:
    """Stores no response rows or secret values—only reviewed metadata."""

    def __init__(self, project_directory: Path) -> None:
        self.root = project_directory.resolve() / ".dashboard" / "metadata"

    def _path(self, kind: str, identifier: str) -> Path:
        if not identifier or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-" for character in identifier):
            raise ValueError("Invalid metadata identifier")
        return self.root / kind / f"{identifier}.json"

    def save_source(self, source: ApiSourceConfig) -> ApiSourceConfig:
        path = self._path("sources", source.id)
        _atomic_json(path, source.model_dump(mode="json"))
        return source

    def get_source(self, source_id: str) -> ApiSourceConfig:
        return ApiSourceConfig.model_validate(self._read("sources", source_id))

    def list_sources(self) -> list[ApiSourceConfig]:
        return [ApiSourceConfig.model_validate(self._read_path(path)) for path in sorted((self.root / "sources").glob("*.json"))]

    def save_inspection(self, record: ApiSourceInspectionRecord) -> ApiSourceInspectionRecord:
        path = self._path("inspections", record.id)
        if path.exists():
            raise ValueError("Inspection records are immutable")
        _atomic_json(path, record.model_dump(mode="json"))
        return record

    def get_inspection(self, inspection_id: str) -> ApiSourceInspectionRecord:
        record = ApiSourceInspectionRecord.model_validate(self._read("inspections", inspection_id))
        if canonical_checksum(record.inspection) != record.inspection_checksum:
            raise ValueError("Inspection checksum validation failed")
        return record

    def save_approval(self, record: ApiSourceApprovalRecord) -> ApiSourceApprovalRecord:
        path = self._path("approvals", record.id)
        if path.exists():
            raise ValueError("Approval records are immutable")
        _atomic_json(path, record.model_dump(mode="json"))
        return record

    def get_approval(self, approval_id: str) -> ApiSourceApprovalRecord:
        return ApiSourceApprovalRecord.model_validate(self._read("approvals", approval_id))

    def verify(self, project_id: UUID, source_id: str, inspection_id: str, approval_id: str) -> tuple[ApiSourceConfig, ApiSourceInspectionRecord, ApiSourceApprovalRecord]:
        source = self.get_source(source_id)
        inspection = self.get_inspection(inspection_id)
        approval = self.get_approval(approval_id)
        checksum = canonical_checksum(source)
        if inspection.project_id != project_id or approval.project_id != project_id:
            raise ValueError("Inspection or approval belongs to another project")
        if inspection.source_id != source_id or approval.source_id != source_id or approval.inspection_id != inspection_id:
            raise ValueError("Inspection or approval belongs to another source")
        if checksum != inspection.source_checksum or checksum != approval.source_checksum:
            raise ValueError("The source changed after inspection; re-inspection is required")
        if inspection.inspection_checksum != approval.inspection_checksum:
            raise ValueError("The inspection changed after approval")
        if not approval.complete:
            raise ValueError("The approval is incomplete")
        inspected = {field.path for field in inspection.inspection.fields}
        if set(approval.field_classifications) != inspected or set(approval.mappings) - inspected:
            raise ValueError("The approval does not cover the inspected source")
        return source, inspection, approval

    def _read(self, kind: str, identifier: str) -> dict:
        path = self._path(kind, identifier)
        if not path.exists():
            raise KeyError(identifier)
        return self._read_path(path)

    @staticmethod
    def _read_path(path: Path) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError("Project metadata is unreadable") from exc
        if not isinstance(payload, dict):
            raise ValueError("Project metadata is invalid")
        return payload
