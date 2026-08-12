"""Temporary one-time artifact lifecycle for confidential local reports."""

from __future__ import annotations

import tempfile
from pathlib import Path
from threading import RLock
from uuid import uuid4

from automation.reports.models import ReportArtifact, ReportRequest
from automation.reports.renderers import render_excel, render_html, render_pdf
from automation.specification.models import OutputKind


MEDIA = {OutputKind.WEB: "text/html", OutputKind.EXCEL: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", OutputKind.PDF: "application/pdf"}
SUFFIX = {OutputKind.WEB: ".html", OutputKind.EXCEL: ".xlsx", OutputKind.PDF: ".pdf"}


class ArtifactStore:
    def __init__(self, temporary_directory: Path | None = None) -> None:
        self.root = temporary_directory or Path(tempfile.mkdtemp(prefix="dashboard-reports-"))
        self._paths: dict[str, Path] = {}
        self._lock = RLock()

    def generate(self, request: ReportRequest) -> list[ReportArtifact]:
        if request.confidential and not request.confidential_lifecycle_approved:
            raise ValueError("Confidential report lifecycle approval is required")
        renderers = {OutputKind.WEB: lambda value: render_html(value).encode(), OutputKind.EXCEL: render_excel, OutputKind.PDF: render_pdf}
        artifacts: list[ReportArtifact] = []
        for output in request.outputs:
            identifier = uuid4().hex
            content = renderers[output](request.document)
            path = self.root / f"{identifier}{SUFFIX[output]}"
            path.write_bytes(content)
            with self._lock:
                self._paths[identifier] = path
            artifacts.append(ReportArtifact(id=identifier, output=output, filename=f"dashboard-report{SUFFIX[output]}", media_type=MEDIA[output], confidential=request.confidential, one_time_download=request.confidential, size_bytes=len(content)))
        return artifacts

    def consume(self, identifier: str) -> tuple[bytes, Path]:
        with self._lock:
            path = self._paths.pop(identifier, None)
        if path is None or not path.exists():
            raise KeyError(identifier)
        content = path.read_bytes()
        path.unlink()
        return content, path


artifact_store = ArtifactStore()
