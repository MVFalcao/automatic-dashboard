"""Hermes-cron reconciliation; the API runner remains the execution receiver."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol

from automation.scheduling.models import ScheduleDefinition, ScheduleFrequency
from automation.scheduling.runner import LocalPipelineRunner
from automation.scheduling.store import ScheduleStore


class JobsClient(Protocol):
    def list_jobs(self) -> list[dict[str, Any]]: ...
    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def update_job(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def delete_job(self, job_id: str) -> None: ...


def _cron(schedule: ScheduleDefinition) -> str:
    if schedule.frequency is ScheduleFrequency.CRON:
        assert schedule.cron_expression
        return schedule.cron_expression
    if schedule.frequency is ScheduleFrequency.DAILY:
        return f"{schedule.minute} {schedule.hour} * * *"
    if schedule.frequency is ScheduleFrequency.WEEKLY:
        assert schedule.weekday is not None
        return f"{schedule.minute} {schedule.hour} * * {(schedule.weekday + 1) % 7}"
    assert schedule.monthday is not None
    return f"{schedule.minute} {schedule.hour} {schedule.monthday} * *"


def managed_job_payload(schedule: ScheduleDefinition, script_name: str) -> dict[str, Any]:
    return {
        "name": f"dashboard-managed-{schedule.id}",
        "schedule": _cron(schedule),
        "timezone": schedule.timezone,
        "script": script_name,
        "no_agent": True,
        "deliver": "local",
        "enabled": True,
    }


class LocalSchedulerService:
    def __init__(self, store: ScheduleStore, runner: LocalPipelineRunner, interval_seconds: float = 30.0) -> None:
        self.store = store
        self.runner = runner
        self.interval_seconds = interval_seconds
        self.jobs_client: JobsClient | None = None
        self.script_directory: Path | None = None

    def set_gateway_client(self, client: JobsClient | None, *, script_directory: Path | None = None) -> None:
        self.jobs_client = client
        self.script_directory = script_directory

    def _script(self, schedule: ScheduleDefinition) -> str:
        if self.script_directory is None:
            raise RuntimeError("Hermes script directory is unavailable")
        name = f"dashboard-{schedule.id}.py"
        destination = self.script_directory / name
        source = f'''import json, os, urllib.request\nrequest = urllib.request.Request(\n    "http://127.0.0.1:8000/api/schedules/{schedule.id}/run",\n    data=b"{{}}", method="POST",\n    headers={{"Authorization": "Bearer " + os.environ["DASHBOARD_LOCAL_AUTH_TOKEN"], "Content-Type": "application/json"}},\n)\nwith urllib.request.urlopen(request, timeout=30) as response:\n    if response.status >= 300: raise RuntimeError("dashboard receiver rejected scheduled tick")\n'''
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".dashboard-script-", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(source)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o700)
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return name

    def start(self) -> None:
        self.store.recover_stale_runs()
        if self.jobs_client is not None:
            self.reconcile()

    def stop(self) -> None:
        return None

    def tick(self, now=None) -> None:
        """Compatibility hook: Hermes cron is the only scheduling authority."""
        if self.jobs_client is not None:
            self.reconcile()

    def reconcile(self) -> None:
        assert self.jobs_client is not None
        remote = {str(item.get("id") or item.get("job_id")): item for item in self.jobs_client.list_jobs()}
        schedules = {item.id: item for item in self.store.list_schedules()}
        bindings = self.store.list_bindings()
        for schedule_id, (job_id, _) in list(bindings.items()):
            schedule = schedules.get(schedule_id)
            if schedule is None or not schedule.enabled:
                if job_id in remote:
                    self.jobs_client.delete_job(job_id)
                self.store.remove_binding(schedule_id)
                if self.script_directory is not None:
                    (self.script_directory / f"dashboard-{schedule_id}.py").unlink(missing_ok=True)
        for schedule in schedules.values():
            if not schedule.enabled:
                continue
            payload = managed_job_payload(schedule, self._script(schedule))
            checksum = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            binding = self.store.get_binding(schedule.id)
            if binding is None or binding[0] not in remote:
                created = self.jobs_client.create_job(payload)
                job_id = str(created.get("id") or created.get("job_id") or "")
                if not job_id:
                    raise RuntimeError("Hermes did not return a managed job id")
                self.store.save_binding(schedule.id, job_id, checksum)
            elif binding[1] != checksum:
                self.jobs_client.update_job(binding[0], payload)
                self.store.save_binding(schedule.id, binding[0], checksum)
