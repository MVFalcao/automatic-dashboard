"""Independent SQLite audit store for applications that do not use schedules."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock

from automation.observability.models import AuditEvent, RunObservation


class ObservabilityStore:
    """Persist only redacted audit and run measurements, never source records."""

    def __init__(self, database: Path | str) -> None:
        self.database = Path(database)
        if str(self.database) != ":memory:":
            self.database.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, action TEXT NOT NULL,
                    actor TEXT NOT NULL, project_id TEXT, run_id TEXT, details_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_observations (
                    run_id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at TEXT NOT NULL,
                    finished_at TEXT, duration_seconds REAL, freshness_at TEXT,
                    token_input INTEGER NOT NULL, token_output INTEGER NOT NULL,
                    token_total INTEGER NOT NULL, failure_class TEXT
                );
                """
            )

    def close(self) -> None:
        self._connection.close()

    def record_audit(self, event: AuditEvent) -> AuditEvent:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO audit_events (id,timestamp,action,actor,project_id,run_id,details_json) VALUES (?,?,?,?,?,?,?)",
                (event.id, event.timestamp.isoformat(), event.action, event.actor, event.project_id, event.run_id,
                 json.dumps(event.details, ensure_ascii=False, separators=(",", ":"))),
            )
        return event

    def list_audit(self, *, project_id: str | None = None, limit: int = 100) -> list[AuditEvent]:
        limit = max(1, min(limit, 1000))
        with self._lock:
            if project_id:
                rows = self._connection.execute("SELECT * FROM audit_events WHERE project_id=? ORDER BY timestamp DESC LIMIT ?", (project_id, limit)).fetchall()
            else:
                rows = self._connection.execute("SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
        return [AuditEvent(id=row["id"], timestamp=row["timestamp"], action=row["action"], actor=row["actor"], project_id=row["project_id"], run_id=row["run_id"], details=json.loads(row["details_json"])) for row in rows]

    record_audit_event = record_audit
    list_audit_events = list_audit

    def record_run(self, observation: RunObservation) -> RunObservation:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT OR REPLACE INTO run_observations
                (run_id,status,started_at,finished_at,duration_seconds,freshness_at,token_input,token_output,token_total,failure_class)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (observation.run_id, observation.status, observation.started_at.isoformat(), observation.finished_at.isoformat() if observation.finished_at else None,
                 observation.duration_seconds, observation.freshness_at.isoformat() if observation.freshness_at else None,
                 observation.token_input, observation.token_output, observation.token_total, observation.failure_class),
            )
        return observation

    def list_runs(self, *, limit: int = 100) -> list[RunObservation]:
        limit = max(1, min(limit, 1000))
        with self._lock:
            rows = self._connection.execute("SELECT * FROM run_observations ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [RunObservation(run_id=row["run_id"], status=row["status"], started_at=row["started_at"], finished_at=row["finished_at"], duration_seconds=row["duration_seconds"], freshness_at=row["freshness_at"], token_input=row["token_input"], token_output=row["token_output"], token_total=row["token_total"], failure_class=row["failure_class"]) for row in rows]
