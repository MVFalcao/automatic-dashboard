"""Separated persistent and short-lived report artifact lifecycle."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, RLock, Thread
from uuid import uuid4

from automation.reports.models import ReportArtifact, ReportRequest
from automation.reports.renderers import render_excel, render_html, render_pdf
from automation.specification.models import OutputKind


MEDIA = {OutputKind.WEB: "text/html", OutputKind.EXCEL: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", OutputKind.PDF: "application/pdf"}
SUFFIX = {OutputKind.WEB: ".html", OutputKind.EXCEL: ".xlsx", OutputKind.PDF: ".pdf"}


class ArtifactStore:
    """Confidential bytes are isolated, expiring, and consumed exactly once."""

    def __init__(self, temporary_directory: Path | None = None, *, ttl: timedelta = timedelta(minutes=10)) -> None:
        self.root = (temporary_directory or Path(tempfile.gettempdir()) / "universal-dashboard-agent" / "confidential-reports").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        self.ttl = ttl
        self._paths: dict[str, tuple[Path, datetime | None, bool]] = {}
        self._lock = RLock()
        self._stop = Event()
        self._sweeper: Thread | None = None

    def start(self) -> None:
        # Every prior file in this dedicated root is an orphan after restart.
        self.delete_orphans()
        if self._sweeper and self._sweeper.is_alive():
            return
        self._stop.clear()
        self._sweeper = Thread(target=self._sweep_loop, name="confidential-report-sweeper", daemon=True)
        self._sweeper.start()

    def stop(self) -> None:
        self._stop.set()
        if self._sweeper:
            self._sweeper.join(timeout=2)
        self._sweeper = None
        self.delete_orphans()

    def delete_orphans(self) -> None:
        with self._lock:
            for path in self.root.iterdir() if self.root.exists() else ():
                if path.is_file() or path.is_symlink():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
            self._paths = {identifier: entry for identifier, entry in self._paths.items() if not entry[2]}

    def _sweep_loop(self) -> None:
        interval = min(30.0, max(0.1, self.ttl.total_seconds() / 2))
        while not self._stop.wait(interval):
            self.cleanup_expired()

    def generate(self, request: ReportRequest) -> list[ReportArtifact]:
        self.cleanup_expired()
        if request.confidential and not request.confidential_lifecycle_approved:
            raise ValueError("Confidential report lifecycle approval is required")
        renderers = {OutputKind.WEB: lambda value: render_html(value).encode(), OutputKind.EXCEL: render_excel, OutputKind.PDF: render_pdf}
        artifacts: list[ReportArtifact] = []
        destination = self.root if request.confidential else request.non_confidential_destination
        if destination is None:
            raise ValueError("Non-confidential reports require an approved local destination")
        destination = destination.expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)
        rendered = [(output, renderers[output](request.document)) for output in request.outputs]
        written: list[str] = []
        try:
            for output, content in rendered:
                identifier = uuid4().hex
                filename = f"dashboard-report-{identifier[:10]}{SUFFIX[output]}"
                path = destination / (f"{identifier}{SUFFIX[output]}" if request.confidential else filename)
                path.write_bytes(content)
                expires = datetime.now(timezone.utc) + self.ttl if request.confidential else None
                with self._lock:
                    self._paths[identifier] = (path, expires, request.confidential)
                written.append(identifier)
                artifacts.append(ReportArtifact(
                    id=identifier, output=output, filename=filename, media_type=MEDIA[output],
                    confidential=request.confidential, one_time_download=request.confidential,
                    size_bytes=len(content), expires_at=expires.isoformat() if expires else None,
                ))
        except Exception:
            for identifier in written:
                self.discard(identifier)
            raise
        return artifacts

    def discard(self, identifier: str) -> None:
        with self._lock:
            entry = self._paths.pop(identifier, None)
        if entry is not None:
            entry[0].unlink(missing_ok=True)

    def consume(self, identifier: str) -> tuple[bytes, Path]:
        with self._lock:
            entry = self._paths.get(identifier)
            if entry and entry[2]:
                self._paths.pop(identifier, None)
        if entry is None:
            raise KeyError(identifier)
        path, expires, confidential = entry
        if not path.exists() or (expires is not None and expires <= datetime.now(timezone.utc)):
            if confidential:
                path.unlink(missing_ok=True)
            raise KeyError(identifier)
        content = path.read_bytes()
        if confidential:
            path.unlink(missing_ok=True)
        return content, path

    def cleanup_expired(self) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            expired = [identifier for identifier, (_, expires, confidential) in self._paths.items() if confidential and expires is not None and expires <= now]
            for identifier in expired:
                path, _, _ = self._paths.pop(identifier)
                path.unlink(missing_ok=True)


artifact_store = ArtifactStore()
