"""JSON-lines logger that redacts before writing to disk or a stream."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from automation.observability.models import LogEvent
from automation.privacy.redaction import redact_payload


class StructuredLogger:
    """Emit one validated, secret-free JSON object per event.

    ``path`` is optional so tests and embedding applications can provide a
    callback or inspect ``events`` without creating files.
    """

    def __init__(self, path: Path | str | None = None, *, logger: logging.Logger | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self.logger = logger
        self.events: list[LogEvent] = []

    def emit(
        self,
        event: str,
        *,
        level: str = "INFO",
        project_id: str | None = None,
        run_id: str | None = None,
        details: Mapping[str, Any] | None = None,
        secrets: Sequence[str] = (),
    ) -> LogEvent:
        sanitized = redact_payload(dict(details or {}), secrets=secrets)
        record = LogEvent(level=level, event=event, project_id=project_id, run_id=run_id, details=sanitized)
        self.events.append(record)
        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        if self.logger is not None:
            self.logger.log(getattr(logging, level), line)
        return record
