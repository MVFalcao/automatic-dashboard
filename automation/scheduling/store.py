"""SQLite persistence for schedule, run, and artifact metadata."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Iterable

from automation.scheduling.models import ArtifactRecord, RunRecord, RunStatus, ScheduleDefinition
from automation.observability.models import AuditEvent


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class ScheduleStore:
    """Thread-safe SQLite repository; project files remain readable YAML/JSON."""

    def __init__(self, database: Path | str) -> None:
        self.database = Path(database)
        if str(self.database) != ":memory:":
            self.database.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.database, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    project_directory TEXT NOT NULL,
                    name TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    hour INTEGER NOT NULL,
                    minute INTEGER NOT NULL,
                    weekday INTEGER,
                    monthday INTEGER,
                    cron_expression TEXT,
                    output_directory TEXT NOT NULL,
                    outputs_json TEXT NOT NULL,
                    retention_limit INTEGER NOT NULL,
                    project_non_confidential_confirmed INTEGER NOT NULL,
                    source_non_confidential_confirmed INTEGER NOT NULL,
                    approval_confirmed INTEGER NOT NULL,
                    approved_by TEXT,
                    enabled INTEGER NOT NULL,
                    notify_on_failure INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    scheduled_for TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    artifact_set_id TEXT,
                    error TEXT,
                    notification_sent INTEGER NOT NULL DEFAULT 0,
                    duration_seconds REAL,
                    freshness_at TEXT,
                    token_input INTEGER NOT NULL DEFAULT 0,
                    token_output INTEGER NOT NULL DEFAULT 0,
                    provider TEXT
                );
                CREATE INDEX IF NOT EXISTS runs_schedule_idx ON runs(schedule_id, started_at DESC);
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    artifact_set_id TEXT NOT NULL,
                    output TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS artifacts_set_idx ON artifacts(schedule_id, artifact_set_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, action TEXT NOT NULL,
                    actor TEXT NOT NULL, project_id TEXT, run_id TEXT, details_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_events_timestamp_idx ON audit_events(timestamp DESC);
                CREATE TABLE IF NOT EXISTS hermes_bindings (
                    schedule_id TEXT PRIMARY KEY REFERENCES schedules(id) ON DELETE CASCADE,
                    job_id TEXT NOT NULL UNIQUE,
                    definition_checksum TEXT NOT NULL,
                    reconciled_at TEXT NOT NULL
                );
                """
            )
            # Additive migration for databases created before observability.
            columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(runs)").fetchall()}
            for name, definition in {
                "duration_seconds": "REAL",
                "freshness_at": "TEXT",
                "token_input": "INTEGER NOT NULL DEFAULT 0",
                "token_output": "INTEGER NOT NULL DEFAULT 0",
                "provider": "TEXT",
            }.items():
                if name not in columns:
                    self._connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")

    @staticmethod
    def _schedule_values(schedule: ScheduleDefinition) -> tuple:
        now = _utc_now()
        created = schedule.created_at or now
        updated = schedule.updated_at or now
        return (
            schedule.id,
            schedule.project_id,
            str(schedule.project_directory),
            schedule.name,
            schedule.frequency.value,
            schedule.timezone,
            schedule.hour,
            schedule.minute,
            schedule.weekday,
            schedule.monthday,
            schedule.cron_expression,
            str(schedule.output_directory),
            json.dumps(schedule.outputs, separators=(",", ":")),
            schedule.retention_limit,
            int(schedule.project_non_confidential_confirmed),
            int(schedule.source_non_confidential_confirmed),
            int(schedule.approval_confirmed),
            schedule.approved_by,
            int(schedule.enabled),
            int(schedule.notify_on_failure),
            _timestamp(created),
            _timestamp(updated),
        )

    def create_schedule(self, schedule: ScheduleDefinition) -> ScheduleDefinition:
        if schedule.enabled and not schedule.can_activate:
            raise ValueError("Scheduling requires explicit non-confidential approval")
        with self._lock, self._connection:
            try:
                self._connection.execute(
                    """INSERT INTO schedules (id, project_id, project_directory, name, frequency,
                    timezone, hour, minute, weekday, monthday, cron_expression, output_directory,
                    outputs_json, retention_limit, project_non_confidential_confirmed,
                    source_non_confidential_confirmed, approval_confirmed, approved_by, enabled,
                    notify_on_failure, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    self._schedule_values(schedule),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Schedule already exists: {schedule.id}") from exc
        return self.get_schedule(schedule.id)

    def get_schedule(self, schedule_id: str) -> ScheduleDefinition:
        with self._lock:
            row = self._connection.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        if row is None:
            raise KeyError(schedule_id)
        return self._schedule_from_row(row)

    def list_schedules(self, *, project_id: str | None = None) -> list[ScheduleDefinition]:
        with self._lock:
            if project_id:
                rows = self._connection.execute("SELECT * FROM schedules WHERE project_id = ? ORDER BY created_at", (project_id,)).fetchall()
            else:
                rows = self._connection.execute("SELECT * FROM schedules ORDER BY created_at").fetchall()
        return [self._schedule_from_row(row) for row in rows]

    def update_schedule(self, schedule: ScheduleDefinition) -> ScheduleDefinition:
        if schedule.enabled and not schedule.can_activate:
            raise ValueError("Scheduling requires explicit non-confidential approval")
        values = list(self._schedule_values(schedule))
        values[-1] = _timestamp(_utc_now())
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """UPDATE schedules SET project_id=?, project_directory=?, name=?, frequency=?, timezone=?,
                hour=?, minute=?, weekday=?, monthday=?, cron_expression=?, output_directory=?, outputs_json=?,
                retention_limit=?, project_non_confidential_confirmed=?, source_non_confidential_confirmed=?,
                approval_confirmed=?, approved_by=?, enabled=?, notify_on_failure=?, updated_at=? WHERE id=?""",
                (*values[1:-2], values[-1], schedule.id),
            )
        if cursor.rowcount == 0:
            raise KeyError(schedule.id)
        return self.get_schedule(schedule.id)

    def delete_schedule(self, schedule_id: str) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        if cursor.rowcount == 0:
            raise KeyError(schedule_id)

    def create_run_if_absent(self, run: RunRecord) -> tuple[RunRecord, bool]:
        """Atomically claim an idempotency key.

        Returns ``(existing, False)`` when another invocation already owns the
        same scheduled execution.
        """
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT OR IGNORE INTO runs (id, schedule_id, idempotency_key, status, scheduled_for,
                started_at, finished_at, artifact_set_id, error, notification_sent, duration_seconds,
                freshness_at, token_input, token_output, provider) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run.id, run.schedule_id, run.idempotency_key, run.status.value, _timestamp(run.scheduled_for),
                 _timestamp(run.started_at), _timestamp(run.finished_at) if run.finished_at else None,
                 run.artifact_set_id, run.error, int(run.notification_sent), run.duration_seconds,
                 _timestamp(run.freshness_at) if run.freshness_at else None, run.token_input, run.token_output, run.provider),
            )
            row = self._connection.execute("SELECT * FROM runs WHERE idempotency_key = ?", (run.idempotency_key,)).fetchone()
        assert row is not None
        return self._run_from_row(row), row["id"] == run.id

    def recover_stale_runs(self, *, older_than: timedelta = timedelta(minutes=30)) -> int:
        """Mark crash-orphaned leases failed before the scheduler resumes."""
        cutoff = _timestamp(_utc_now() - older_than)
        finished = _timestamp(_utc_now())
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """UPDATE runs SET status=?, finished_at=?, error=?
                WHERE status=? AND started_at<?""",
                (RunStatus.FAILED.value, finished, "CrashRecovery: stale running lease recovered", RunStatus.RUNNING.value, cutoff),
            )
        return cursor.rowcount

    def update_run(self, run: RunRecord) -> RunRecord:
        with self._lock, self._connection:
            self._connection.execute(
                """UPDATE runs SET status=?, finished_at=?, artifact_set_id=?, error=?, notification_sent=?,
                duration_seconds=?, freshness_at=?, token_input=?, token_output=?, provider=? WHERE id=?""",
                (run.status.value, _timestamp(run.finished_at) if run.finished_at else None, run.artifact_set_id,
                 run.error, int(run.notification_sent), run.duration_seconds,
                 _timestamp(run.freshness_at) if run.freshness_at else None, run.token_input, run.token_output,
                 run.provider, run.id),
            )
        return self.get_run(run.id)

    def get_run(self, run_id: str) -> RunRecord:
        with self._lock:
            row = self._connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._run_from_row(row)

    def list_runs(self, *, schedule_id: str | None = None, limit: int = 100) -> list[RunRecord]:
        limit = max(1, min(limit, 1000))
        with self._lock:
            if schedule_id:
                rows = self._connection.execute("SELECT * FROM runs WHERE schedule_id = ? ORDER BY started_at DESC LIMIT ?", (schedule_id, limit)).fetchall()
            else:
                rows = self._connection.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._run_from_row(row) for row in rows]

    def record_audit(self, event: AuditEvent) -> AuditEvent:
        """Append a validated, redacted approval or run event."""
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO audit_events (id,timestamp,action,actor,project_id,run_id,details_json) VALUES (?,?,?,?,?,?,?)",
                (event.id, _timestamp(event.timestamp), event.action, event.actor, event.project_id, event.run_id,
                 json.dumps(event.details, ensure_ascii=False, separators=(",", ":"))),
            )
        return event

    def list_audit(self, *, project_id: str | None = None, run_id: str | None = None, limit: int = 100) -> list[AuditEvent]:
        limit = max(1, min(limit, 1000))
        with self._lock:
            clauses: list[str] = []
            values: list[str | int] = []
            if project_id:
                clauses.append("project_id=?")
                values.append(project_id)
            if run_id:
                clauses.append("run_id=?")
                values.append(run_id)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = self._connection.execute(
                f"SELECT * FROM audit_events{where} ORDER BY timestamp DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
        return [AuditEvent(
            id=row["id"], timestamp=row["timestamp"], action=row["action"], actor=row["actor"],
            project_id=row["project_id"], run_id=row["run_id"], details=json.loads(row["details_json"]),
        ) for row in rows]

    # Explicit aliases make the audit boundary discoverable to API callers.
    record_audit_event = record_audit
    list_audit_events = list_audit

    def add_artifacts(self, artifacts: Iterable[ArtifactRecord]) -> None:
        values = [
            (item.id, item.schedule_id, item.run_id, item.artifact_set_id, item.output, str(item.path), _timestamp(item.created_at), item.size_bytes)
            for item in artifacts
        ]
        with self._lock, self._connection:
            self._connection.executemany(
                "INSERT INTO artifacts (id, schedule_id, run_id, artifact_set_id, output, path, created_at, size_bytes) VALUES (?,?,?,?,?,?,?,?)",
                values,
            )

    def remove_artifacts_for_run(self, run_id: str) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM artifacts WHERE run_id=?", (run_id,))

    def list_artifacts(self, *, schedule_id: str, artifact_set_id: str | None = None) -> list[ArtifactRecord]:
        with self._lock:
            if artifact_set_id:
                rows = self._connection.execute("SELECT * FROM artifacts WHERE schedule_id=? AND artifact_set_id=? ORDER BY created_at", (schedule_id, artifact_set_id)).fetchall()
            else:
                rows = self._connection.execute("SELECT * FROM artifacts WHERE schedule_id=? ORDER BY created_at DESC", (schedule_id,)).fetchall()
        return [self._artifact_from_row(row) for row in rows]

    def successful_artifact_sets(self, schedule_id: str) -> list[str]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT artifact_set_id FROM runs WHERE schedule_id=? AND status=? AND artifact_set_id IS NOT NULL
                ORDER BY finished_at DESC""", (schedule_id, RunStatus.SUCCEEDED.value)
            ).fetchall()
        return [str(row["artifact_set_id"]) for row in rows]

    def remove_artifact_set(self, schedule_id: str, artifact_set_id: str) -> list[Path]:
        artifacts = self.list_artifacts(schedule_id=schedule_id, artifact_set_id=artifact_set_id)
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM artifacts WHERE schedule_id=? AND artifact_set_id=?", (schedule_id, artifact_set_id))
        return [item.path for item in artifacts]

    def get_binding(self, schedule_id: str) -> tuple[str, str] | None:
        with self._lock:
            row = self._connection.execute("SELECT job_id, definition_checksum FROM hermes_bindings WHERE schedule_id=?", (schedule_id,)).fetchone()
        return (row["job_id"], row["definition_checksum"]) if row else None

    def save_binding(self, schedule_id: str, job_id: str, checksum: str) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO hermes_bindings(schedule_id,job_id,definition_checksum,reconciled_at)
                VALUES(?,?,?,?) ON CONFLICT(schedule_id) DO UPDATE SET
                job_id=excluded.job_id, definition_checksum=excluded.definition_checksum,
                reconciled_at=excluded.reconciled_at""",
                (schedule_id, job_id, checksum, _timestamp(_utc_now())),
            )

    def remove_binding(self, schedule_id: str) -> tuple[str, str] | None:
        binding = self.get_binding(schedule_id)
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM hermes_bindings WHERE schedule_id=?", (schedule_id,))
        return binding

    def list_bindings(self) -> dict[str, tuple[str, str]]:
        with self._lock:
            rows = self._connection.execute("SELECT schedule_id,job_id,definition_checksum FROM hermes_bindings").fetchall()
        return {row["schedule_id"]: (row["job_id"], row["definition_checksum"]) for row in rows}

    @staticmethod
    def _schedule_from_row(row: sqlite3.Row) -> ScheduleDefinition:
        return ScheduleDefinition(
            id=row["id"], project_id=row["project_id"], project_directory=Path(row["project_directory"]), name=row["name"],
            frequency=row["frequency"], timezone=row["timezone"], hour=row["hour"], minute=row["minute"], weekday=row["weekday"],
            monthday=row["monthday"], cron_expression=row["cron_expression"], output_directory=Path(row["output_directory"]),
            outputs=json.loads(row["outputs_json"]), retention_limit=row["retention_limit"],
            project_non_confidential_confirmed=bool(row["project_non_confidential_confirmed"]),
            source_non_confidential_confirmed=bool(row["source_non_confidential_confirmed"]), approval_confirmed=bool(row["approval_confirmed"]),
            approved_by=row["approved_by"], enabled=bool(row["enabled"]), notify_on_failure=bool(row["notify_on_failure"]),
            created_at=_datetime(row["created_at"]), updated_at=_datetime(row["updated_at"]),
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=row["id"], schedule_id=row["schedule_id"], idempotency_key=row["idempotency_key"], status=row["status"],
            scheduled_for=datetime.fromisoformat(row["scheduled_for"]), started_at=datetime.fromisoformat(row["started_at"]),
            finished_at=_datetime(row["finished_at"]), artifact_set_id=row["artifact_set_id"], error=row["error"], notification_sent=bool(row["notification_sent"]),
            duration_seconds=row["duration_seconds"], freshness_at=_datetime(row["freshness_at"]),
            token_input=row["token_input"], token_output=row["token_output"], provider=row["provider"],
        )

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> ArtifactRecord:
        return ArtifactRecord(
            id=row["id"], schedule_id=row["schedule_id"], run_id=row["run_id"], artifact_set_id=row["artifact_set_id"],
            output=row["output"], path=Path(row["path"]), created_at=datetime.fromisoformat(row["created_at"]), size_bytes=row["size_bytes"],
        )
