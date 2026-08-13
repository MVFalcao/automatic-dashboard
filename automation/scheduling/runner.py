"""Idempotent local pipeline execution and successful-artifact retention."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Protocol, Sequence
from uuid import uuid4

from automation.scheduling.models import ArtifactRecord, PipelineArtifact, RunRecord, RunStatus, ScheduleDefinition
from automation.scheduling.store import ScheduleStore
from automation.observability.logging import StructuredLogger
from automation.observability.models import AuditEvent


class PipelineExecutor(Protocol):
    def __call__(self, schedule: ScheduleDefinition) -> Sequence[PipelineArtifact] | "PipelineExecution": ...


@dataclass(frozen=True)
class PipelineExecution:
    """Optional production metadata returned alongside deterministic artifacts."""

    artifacts: Sequence[PipelineArtifact]
    freshness_at: datetime | None = None
    token_input: int = 0
    token_output: int = 0
    provider: str | None = None
    pending_checkpoint_source_id: str | None = None
    pending_checkpoint: str | int | float | None = None
    project_id: str | None = None
    project_directory: Path | None = None


class NotificationSink(Protocol):
    def notify_failure(self, schedule: ScheduleDefinition, run: RunRecord) -> bool: ...


class OsNotificationSink:
    """Best-effort Windows/Linux notification with no delivery dependency."""

    def notify_failure(self, schedule: ScheduleDefinition, run: RunRecord) -> bool:
        title = "Dashboard scheduled run failed"
        message = run.error or "The scheduled report could not be generated."
        try:
            if sys.platform.startswith("win"):
                # PowerShell is already present on supported Windows versions;
                # Pass message values through the environment rather than
                # interpolating them into PowerShell source.
                script = "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; $n=New-Object System.Windows.Forms.NotifyIcon; $n.Icon=[System.Drawing.SystemIcons]::Warning; $n.Visible=$true; $n.ShowBalloonTip(5000,$env:DASHBOARD_NOTIFY_TITLE,$env:DASHBOARD_NOTIFY_MESSAGE,[System.Windows.Forms.ToolTipIcon]::Warning)"
                environment = {"DASHBOARD_NOTIFY_TITLE": title, "DASHBOARD_NOTIFY_MESSAGE": message[:240]}
                completed = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=False, capture_output=True, timeout=10, env={**os.environ, **environment})
                return completed.returncode == 0
            if sys.platform.startswith("linux") and shutil.which("notify-send"):
                completed = subprocess.run(["notify-send", title, message[:240]], check=False, capture_output=True, timeout=10)
                return completed.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
        return False


class LocalPipelineRunner:
    """Run an approved schedule and never replace artifacts after a failure."""

    def __init__(
        self,
        store: ScheduleStore,
        executor: PipelineExecutor | None = None,
        notifier: NotificationSink | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self.store = store
        self.executor = executor
        self.notifier = notifier or OsNotificationSink()
        self.logger = logger or StructuredLogger()

    @staticmethod
    def _key(schedule_id: str, scheduled_for: datetime) -> str:
        instant = scheduled_for.astimezone(timezone.utc).replace(second=0, microsecond=0)
        return f"{schedule_id}:{instant.isoformat()}"

    def run(self, schedule_id: str, *, scheduled_for: datetime | None = None) -> RunRecord:
        schedule = self.store.get_schedule(schedule_id)
        if not schedule.enabled:
            raise ValueError("Schedule is not active")
        if not schedule.can_activate:
            raise ValueError("Scheduling requires explicit non-confidential approval")
        due = scheduled_for or datetime.now(timezone.utc)
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        started = datetime.now(timezone.utc)
        run = RunRecord(
            schedule_id=schedule.id,
            idempotency_key=self._key(schedule.id, due),
            status=RunStatus.RUNNING,
            scheduled_for=due,
            started_at=started,
        )
        run, claimed = self.store.create_run_if_absent(run)
        if not claimed:
            return run
        self.store.record_audit(AuditEvent(
            action="run_started", project_id=schedule.project_id, run_id=run.id,
            details={"schedule_id": schedule.id, "scheduled_for": due.isoformat()},
        ))
        self.logger.emit("run_started", project_id=schedule.project_id, run_id=run.id, details={"schedule_id": schedule.id})
        written: list[Path] = []
        staged: list[tuple[Path, Path]] = []
        backups: list[tuple[Path, Path]] = []
        previous_project = None
        try:
            if self.executor is None:
                raise RuntimeError("No local pipeline executor is configured")
            outcome = self.executor(schedule)
            execution = outcome if isinstance(outcome, PipelineExecution) else PipelineExecution(artifacts=list(outcome))
            generated = list(execution.artifacts)
            if not generated:
                raise RuntimeError("The local pipeline returned no report artifacts")
            artifact_set_id = uuid4().hex
            destination = schedule.output_directory.resolve()
            destination.mkdir(parents=True, exist_ok=True)
            records: list[ArtifactRecord] = []
            staging = destination / ".dashboard-staging" / run.id
            staging.mkdir(parents=True, exist_ok=False)
            for artifact in generated:
                if artifact.output not in schedule.outputs:
                    raise ValueError(f"Pipeline produced an unselected output: {artifact.output}")
                target = (destination / artifact.filename).resolve()
                if target.parent != destination:
                    raise ValueError("Pipeline artifact escaped the selected output folder")
                temporary = staging / artifact.filename
                temporary.write_bytes(artifact.content)
                staged.append((temporary, target))
                records.append(ArtifactRecord(
                    schedule_id=schedule.id,
                    run_id=run.id,
                    artifact_set_id=artifact_set_id,
                    output=artifact.output,
                    path=target,
                    created_at=datetime.now(timezone.utc),
                    size_bytes=len(artifact.content),
                ))
            # Promote the complete set only after every artifact has rendered.
            # Backups make the promotion reversible if the filesystem fails
            # midway, preserving the last successful report set.
            for temporary, target in staged:
                backup = staging / f".{target.name}.previous"
                if target.exists():
                    target.replace(backup)
                    backups.append((backup, target))
                temporary.replace(target)
                written.append(target)
            self.store.add_artifacts(records)
            previous_project = self._commit_pending_metadata(execution, artifact_set_id)
            shutil.rmtree(staging, ignore_errors=True)
            finished = datetime.now(timezone.utc)
            run = run.model_copy(update={
                "status": RunStatus.SUCCEEDED, "finished_at": finished, "artifact_set_id": artifact_set_id,
                "duration_seconds": max(0.0, (finished - started).total_seconds()),
                "freshness_at": execution.freshness_at, "token_input": execution.token_input,
                "token_output": execution.token_output, "provider": execution.provider,
            })
            self.store.update_run(run)
            self.store.record_audit(AuditEvent(action="run_succeeded", project_id=schedule.project_id, run_id=run.id, details={
                "duration_seconds": run.duration_seconds, "artifact_set_id": artifact_set_id,
                "token_input": run.token_input, "token_output": run.token_output,
            }))
            self.logger.emit("run_succeeded", project_id=schedule.project_id, run_id=run.id, details={"duration_seconds": run.duration_seconds, "artifact_count": len(records)})
            self._retain_successful_sets(schedule)
            return self.store.get_run(run.id)

        except Exception as exc:
            # Remove only files created by this failed run; existing successful
            # report sets are intentionally untouched.
            for path in written:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            for backup, target in backups:
                try:
                    if target.exists():
                        target.unlink()
                    backup.replace(target)
                except OSError:
                    pass
            if 'staging' in locals():
                shutil.rmtree(staging, ignore_errors=True)
            self.store.remove_artifacts_for_run(run.id)
            if previous_project is not None:
                from dashboard.api.projects import ProjectRepository
                ProjectRepository().save(previous_project)
            # Exception text can contain source records (or credentials) from
            # an adapter.  SQLite history is operational metadata, so retain
            # the exception class but never persist its arbitrary message.
            safe_error = f"{type(exc).__name__}: scheduled pipeline failed"
            finished = datetime.now(timezone.utc)
            run = run.model_copy(update={"status": RunStatus.FAILED, "finished_at": finished, "error": safe_error, "duration_seconds": max(0.0, (finished - started).total_seconds())})
            if schedule.notify_on_failure:
                run = run.model_copy(update={"notification_sent": bool(self.notifier.notify_failure(schedule, run))})
            self.store.update_run(run)
            self.store.record_audit(AuditEvent(action="run_failed", project_id=schedule.project_id, run_id=run.id, details={"failure_class": type(exc).__name__}))
            self.logger.emit("run_failed", level="ERROR", project_id=schedule.project_id, run_id=run.id, details={"failure_class": type(exc).__name__})
            return self.store.get_run(run.id)

    @staticmethod
    def _commit_pending_metadata(execution: PipelineExecution, artifact_set_id: str):
        if execution.pending_checkpoint_source_id is None:
            return None
        if execution.project_id is None or execution.project_directory is None:
            raise RuntimeError("Pending pipeline metadata is missing its project reference")
        from uuid import UUID
        from dashboard.api.projects import ProjectRepository

        repository = ProjectRepository()
        project = repository.load(execution.project_directory)
        if project.id != UUID(execution.project_id):
            raise RuntimeError("Pending pipeline metadata belongs to another project")
        checkpoints = dict(project.checkpoints)
        checkpoints[execution.pending_checkpoint_source_id] = execution.pending_checkpoint
        repository.save(project.model_copy(update={
            "checkpoints": checkpoints,
            "last_successful_artifact_set_id": artifact_set_id,
        }))
        return project

    def _retain_successful_sets(self, schedule: ScheduleDefinition) -> None:
        successful = self.store.successful_artifact_sets(schedule.id)
        for artifact_set_id in successful[schedule.retention_limit:]:
            paths = self.store.remove_artifact_set(schedule.id, artifact_set_id)
            retained_paths = {item.path.resolve() for item in self.store.list_artifacts(schedule_id=schedule.id)}
            for path in paths:
                try:
                    if path.resolve() not in retained_paths:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
