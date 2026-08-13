"""Process-local, value-free events for redacted support diagnostics."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from automation.privacy.redaction import redact_payload


_ALLOWED_DETAILS = frozenset({"attempt", "code", "component", "failure_class", "status"})


class SupportEventBuffer:
    """Keep a small operational trail without project data or subprocess output."""

    def __init__(self, limit: int = 100) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=limit)
        self._lock = RLock()

    def record(self, event: str, *, level: str = "INFO", details: dict[str, Any] | None = None) -> None:
        safe_details = {key: value for key, value in (details or {}).items() if key in _ALLOWED_DETAILS}
        item = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event[:80],
            "level": level if level in {"INFO", "WARNING", "ERROR"} else "INFO",
            "details": redact_payload(safe_details),
        }
        with self._lock:
            self._events.append(item)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)


support_events = SupportEventBuffer()
