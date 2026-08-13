"""Server-constructed local report generation and download endpoints."""

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from automation.pipeline import ProductionPipelineExecutor
from automation.reports.models import ReportArtifact, ReportRequest
from automation.reports.service import artifact_store
from automation.specification.models import OutputKind
from dashboard.api.projects import project_repository


class ProjectReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: UUID
    specification_version: int = Field(ge=1)
    outputs: list[OutputKind] = Field(min_length=1)
    filter_values: dict[str, Any] = Field(default_factory=dict)
    non_confidential_destination: Path | None = None
    confidential_lifecycle_approved: bool = False


router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.post("", response_model=list[ReportArtifact], status_code=201)
def generate_reports(payload: ProjectReportRequest) -> list[ReportArtifact]:
    try:
        project = project_repository.get(payload.project_id)
        built_project, source, sync, document = ProductionPipelineExecutor().build_document(
            project.project_directory,
            specification_version=payload.specification_version,
            filter_values=payload.filter_values,
        )
        confidential = bool(document.specification.privacy.confidential_fields)
        if not confidential:
            destination = payload.non_confidential_destination
            if destination is None:
                raise ValueError("Choose the approved local folder for non-confidential reports")
            destination = destination.expanduser().resolve()
            # The project directory itself or a selected descendant is an
            # approved local persistence boundary. External folders must be
            # separately selected in the request and remain local paths.
            if not destination.is_absolute():
                raise ValueError("Report destination must be an absolute local path")
        else:
            destination = None
        request = ReportRequest(
            document=document, outputs=payload.outputs,
            confidential=confidential,
            confidential_lifecycle_approved=payload.confidential_lifecycle_approved,
            non_confidential_destination=destination,
        )
        artifacts = artifact_store.generate(request)
        try:
            checkpoints = dict(built_project.checkpoints)
            checkpoints[source.id] = sync.next_checkpoint
            project_repository.save(built_project.model_copy(update={
                "checkpoints": checkpoints,
                "last_successful_artifact_set_id": artifacts[0].id if artifacts else built_project.last_successful_artifact_set_id,
            }))
        except Exception:
            for artifact in artifacts:
                artifact_store.discard(artifact.id)
            raise
        return artifacts
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{artifact_id}/download")
def download_report(artifact_id: str) -> Response:
    try:
        content, path = artifact_store.consume(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Report artifact not found or already downloaded") from exc
    media = {".html": "text/html", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".pdf": "application/pdf"}[path.suffix]
    return Response(content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{path.name}"'})
