"""Loopback report generation and one-time download endpoints."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from automation.reports.models import ReportArtifact, ReportRequest
from automation.reports.service import artifact_store


router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.post("", response_model=list[ReportArtifact], status_code=201)
def generate_reports(payload: ReportRequest) -> list[ReportArtifact]:
    try:
        return artifact_store.generate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{artifact_id}/download")
def download_report(artifact_id: str) -> Response:
    try:
        content, path = artifact_store.consume(artifact_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Report artifact not found or already downloaded") from exc
    media = {".html": "text/html", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".pdf": "application/pdf"}[path.suffix]
    return Response(content=content, media_type=media)
