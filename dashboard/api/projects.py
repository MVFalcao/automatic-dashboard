"""Restart-safe, secret-free project aggregate storage."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from dashboard.api.models import Language, OutputFormat
from dashboard.api.storage import safe_project_name


class ProjectDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=120)
    language: Language
    outputs: list[OutputFormat] = Field(min_length=1)
    project_directory: Path
    active_specification_version: int | None = Field(default=None, ge=1)
    source_ids: list[str] = Field(default_factory=list)
    approval_ids: list[str] = Field(default_factory=list)
    schedule_ids: list[str] = Field(default_factory=list)
    terminology: dict[str, str] = Field(default_factory=dict)
    colors: list[str] = Field(default_factory=list)
    non_confidential_confirmed: bool = False


class ProjectRepository:
    def __init__(self) -> None:
        self._lock = RLock()

    @staticmethod
    def _path(project: ProjectDefinition) -> Path:
        return project.project_directory / "project.yaml"

    def save(self, project: ProjectDefinition) -> ProjectDefinition:
        destination = self._path(project)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = project.model_dump(mode="json")
        fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".project-", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return project

    def load(self, directory: Path) -> ProjectDefinition:
        path = directory / "project.yaml"
        if not path.exists():
            raise KeyError(directory)
        return ProjectDefinition.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


project_repository = ProjectRepository()
_projects: dict[UUID, ProjectDefinition] = {}
router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=ProjectDefinition, status_code=201)
def create_project(project: ProjectDefinition) -> ProjectDefinition:
    project.project_directory.mkdir(parents=True, exist_ok=True)
    project_repository.save(project)
    _projects[project.id] = project
    return project


@router.get("/{project_id}", response_model=ProjectDefinition)
def get_project(project_id: UUID) -> ProjectDefinition:
    project = _projects.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    try:
        return project_repository.load(project.project_directory)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project definition not found") from exc


@router.put("/{project_id}", response_model=ProjectDefinition)
def update_project(project_id: UUID, project: ProjectDefinition) -> ProjectDefinition:
    if project.id != project_id:
        raise HTTPException(status_code=400, detail="Project id does not match URL")
    project_repository.save(project)
    _projects[project_id] = project
    return project
