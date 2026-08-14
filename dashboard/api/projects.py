"""Restart-safe, schema-versioned, secret-free project aggregate storage."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import UUID, uuid4

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from automation.specification.models import DashboardSpec
from automation.specification.versioning import load_active_spec
from dashboard.api.models import Language, OutputFormat


PROJECT_SCHEMA_VERSION = 2


def _default_registry_path() -> Path:
    configured = os.environ.get("DASHBOARD_PROJECT_REGISTRY")
    if configured:
        return Path(configured)
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return root / "universal-dashboard-agent" / "projects.json"


def _atomic_text(destination: Path, content: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=f".{destination.name}-", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


class ProjectDefinition(BaseModel):
    """Project metadata only; records, report values, prompts and secrets are forbidden."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[PROJECT_SCHEMA_VERSION] = PROJECT_SCHEMA_VERSION
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    language: Language
    outputs: list[OutputFormat] = Field(min_length=1)
    project_directory: Path
    active_specification_version: int | None = Field(default=None, ge=1)
    specification_versions: list[int] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    active_source_id: str | None = None
    active_source_inspection_id: str | None = None
    active_source_approval_id: str | None = None
    inspection_ids: list[str] = Field(default_factory=list)
    approval_ids: list[str] = Field(default_factory=list)
    schedule_ids: list[str] = Field(default_factory=list)
    provider_ids: list[str] = Field(default_factory=list)
    drift_draft_ids: list[str] = Field(default_factory=list)
    checkpoints: dict[str, str | int | float | None] = Field(default_factory=dict)
    last_successful_artifact_set_id: str | None = Field(default=None, max_length=160)
    terminology: dict[str, str] = Field(default_factory=dict)
    colors: list[str] = Field(default_factory=list)
    layouts: dict[str, dict[str, int | str | float | bool]] = Field(default_factory=dict)
    non_confidential_confirmed: bool = False

    @field_validator("project_directory")
    @classmethod
    def absolute_project_directory(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("Use an absolute local project path, for example C:\\Users\\Name\\Documents\\DashboardProject")
        return value.resolve()


class ProjectRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    project_directory: Path


class OpenProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_directory: Path


class ApproveSpecificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specification: Any
    approval_id: UUID
    approved_by: str = Field(min_length=1, max_length=160)
    confirmed_non_confidential: bool = False


class ProjectWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: ProjectDefinition
    specification: DashboardSpec


class ProjectRepository:
    def __init__(self, registry_path: Path | None = None) -> None:
        self.registry_path = (registry_path or _default_registry_path()).resolve()
        self._lock = RLock()

    @staticmethod
    def _paths(directory: Path) -> tuple[Path, Path]:
        return directory / "project.yaml", directory / "project.json"

    def _registry(self) -> list[ProjectRegistryEntry]:
        if not self.registry_path.exists():
            return []
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
            return [ProjectRegistryEntry.model_validate(item) for item in payload.get("projects", [])]
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError("The local project registry is unreadable") from exc

    def _write_registry(self, entries: list[ProjectRegistryEntry]) -> None:
        payload = {"schema_version": 1, "projects": [entry.model_dump(mode="json") for entry in entries]}
        _atomic_text(self.registry_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    def register(self, project: ProjectDefinition) -> None:
        entries = [entry for entry in self._registry() if entry.id != project.id and entry.project_directory != project.project_directory]
        entries.append(ProjectRegistryEntry(id=project.id, name=project.name, project_directory=project.project_directory))
        self._write_registry(sorted(entries, key=lambda item: (item.name.casefold(), str(item.id))))

    def list(self) -> list[ProjectRegistryEntry]:
        with self._lock:
            return self._registry()

    def save(self, project: ProjectDefinition) -> ProjectDefinition:
        destination = project.project_directory / "project.yaml"
        payload = project.model_dump(mode="json")
        with self._lock:
            _atomic_text(destination, yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))
            self.register(project)
        return project

    def _read_payload(self, directory: Path) -> tuple[Path, dict[str, Any]]:
        yaml_path, json_path = self._paths(directory)
        path = yaml_path if yaml_path.exists() else json_path
        if not path.exists():
            raise KeyError(directory)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.suffix == ".yaml" else json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise ValueError("Project definition is unreadable") from exc
        if not isinstance(raw, dict):
            raise ValueError("Project definition must be an object")
        return path, raw

    def _migrate(self, directory: Path, path: Path, raw: dict[str, Any]) -> ProjectDefinition:
        version = raw.get("schema_version")
        if version == PROJECT_SCHEMA_VERSION:
            return ProjectDefinition.model_validate(raw)
        if version not in {None, 1}:
            raise ValueError(f"Unsupported project schema version: {version}")
        backup = path.with_name(f"{path.name}.pre-v{PROJECT_SCHEMA_VERSION}.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        migrated = {
            "schema_version": PROJECT_SCHEMA_VERSION,
            "id": raw.get("id", str(uuid4())),
            "name": raw.get("name", directory.name),
            "language": raw.get("language", "en"),
            "outputs": raw.get("outputs", ["web"]),
            "project_directory": str(directory.resolve()),
            "active_specification_version": raw.get("active_specification_version"),
            "source_ids": raw.get("source_ids", []),
            "active_source_id": raw.get("active_source_id"),
            "active_source_inspection_id": raw.get("active_source_inspection_id"),
            "active_source_approval_id": raw.get("active_source_approval_id"),
            "approval_ids": raw.get("approval_ids", []),
            "schedule_ids": raw.get("schedule_ids", []),
            "terminology": raw.get("terminology", {}),
            "colors": raw.get("colors", []),
            "non_confidential_confirmed": raw.get("non_confidential_confirmed", False),
        }
        project = ProjectDefinition.model_validate(migrated)
        self.save(project)
        return project

    def load(self, directory: Path) -> ProjectDefinition:
        directory = directory.expanduser().resolve()
        with self._lock:
            path, raw = self._read_payload(directory)
            project = self._migrate(directory, path, raw)
            self.register(project)
            return project

    def get(self, project_id: UUID) -> ProjectDefinition:
        with self._lock:
            entry = next((item for item in self._registry() if item.id == project_id), None)
            if entry is None:
                raise KeyError(project_id)
            return self.load(entry.project_directory)


project_repository = ProjectRepository()
router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRegistryEntry])
def list_projects() -> list[ProjectRegistryEntry]:
    return project_repository.list()


@router.post("", response_model=ProjectDefinition, status_code=201)
def create_project(project: ProjectDefinition) -> ProjectDefinition:
    try:
        return project_repository.save(project)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/open", response_model=ProjectDefinition)
def open_project(payload: OpenProjectRequest) -> ProjectDefinition:
    try:
        return project_repository.load(payload.project_directory)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project definition not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{project_id}", response_model=ProjectDefinition)
def get_project(project_id: UUID) -> ProjectDefinition:
    try:
        return project_repository.get(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc


@router.get("/{project_id}/workspace", response_model=ProjectWorkspace)
def get_project_workspace(project_id: UUID) -> ProjectWorkspace:
    """Open a registered project with its checksum-verified active spec."""

    try:
        project = project_repository.get(project_id)
        if project.active_specification_version is None:
            raise FileNotFoundError
        specification = load_active_spec(project.project_directory)
        return ProjectWorkspace(project=project, specification=specification)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail="The project does not have a readable active dashboard specification.",
        ) from exc


@router.put("/{project_id}", response_model=ProjectDefinition)
def update_project(project_id: UUID, project: ProjectDefinition) -> ProjectDefinition:
    if project.id != project_id:
        raise HTTPException(status_code=400, detail="Project id does not match URL")
    try:
        current = project_repository.get(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    if current.project_directory != project.project_directory:
        raise HTTPException(status_code=409, detail="A project directory cannot be changed after creation")
    return project_repository.save(project)


@router.post("/{project_id}/specifications", status_code=201)
def approve_specification(project_id: UUID, payload: ApproveSpecificationRequest) -> dict[str, Any]:
    from automation.approval.service import approval_store
    from automation.specification.models import DashboardSpec
    from automation.specification.versioning import save_approved_spec

    try:
        project = project_repository.get(project_id)
        approval = approval_store.get(payload.approval_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project or approval not found") from exc
    if not approval.ready_to_activate:
        raise HTTPException(status_code=409, detail="Every section must be approved before specification activation")
    try:
        specification = DashboardSpec.model_validate(payload.specification)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="The proposed specification is invalid") from exc
    approved_sections = set(approval.sections)
    if {section.id for section in specification.sections} != approved_sections:
        raise HTTPException(status_code=409, detail="Specification sections do not match the reviewed approval package")
    confidential = bool(specification.privacy.confidential_fields)
    if not confidential and not payload.confirmed_non_confidential:
        raise HTTPException(status_code=409, detail="Non-confidential persistence requires explicit confirmation")
    metadata = save_approved_spec(
        project.project_directory, specification,
        approved_by=payload.approved_by, approval_id=str(approval.approval_id),
    )
    versions = [*project.specification_versions, metadata.version]
    project_repository.save(project.model_copy(update={
        "active_specification_version": metadata.version,
        "specification_versions": sorted(set(versions)),
    }))
    return metadata.model_dump(mode="json")


@router.post("/{project_id}/specifications/{version}/rollback", response_model=ProjectDefinition)
def rollback_project_specification(project_id: UUID, version: int) -> ProjectDefinition:
    from automation.specification.versioning import rollback_spec
    try:
        project = project_repository.get(project_id)
        if version not in project.specification_versions:
            raise KeyError(version)
        rollback_spec(project.project_directory, version)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Approved specification version not found") from exc
    return project_repository.save(project.model_copy(update={"active_specification_version": version}))
