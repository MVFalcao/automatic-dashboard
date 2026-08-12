from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from automation.scheduling.cron import CronError, preview_schedule
from automation.scheduling.models import PipelineArtifact, RunStatus, ScheduleDefinition, ScheduleFrequency
from automation.scheduling.runner import LocalPipelineRunner
from automation.scheduling.store import ScheduleStore


def definition(tmp_path: Path, **changes) -> ScheduleDefinition:
    values = {
        "id": "schedule-1",
        "project_id": "project-1",
        "project_directory": tmp_path / "project",
        "name": "Daily report",
        "frequency": ScheduleFrequency.DAILY,
        "timezone": "America/Sao_Paulo",
        "hour": 9,
        "minute": 30,
        "output_directory": tmp_path / "reports",
        "outputs": ["xlsx", "pdf"],
        "project_non_confidential_confirmed": True,
        "source_non_confidential_confirmed": True,
        "approval_confirmed": True,
        "approved_by": "owner",
        "enabled": True,
    }
    values.update(changes)
    return ScheduleDefinition(**values)


def test_activation_requires_both_non_confidential_confirmations() -> None:
    with pytest.raises(ValueError, match="non-confidential"):
        ScheduleDefinition(
            project_id="project", project_directory=".", name="Blocked", frequency="daily",
            output_directory="reports", outputs=["pdf"], enabled=True, approval_confirmed=True, approved_by="owner",
        )


def test_preset_and_cron_previews_are_timezone_aware(tmp_path: Path) -> None:
    after = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    weekly = definition(tmp_path, frequency="weekly", weekday=0, hour=9, minute=0)
    dates = preview_schedule(weekly, after=after, count=2)
    assert [date.weekday() for date in dates] == [0, 0]
    assert all(str(date.tzinfo) == "America/Sao_Paulo" for date in dates)

    cron = definition(tmp_path, id="cron", frequency="cron", cron_expression="*/15 8-9 * * 1-5")
    assert len(preview_schedule(cron, after=after, count=4)) == 4
    bad = definition(tmp_path, id="bad", frequency="cron", cron_expression="every morning")
    with pytest.raises(CronError):
        preview_schedule(bad, after=after, count=1)


def test_store_persists_secret_free_schedule_and_runs(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    store = ScheduleStore(database)
    schedule = definition(tmp_path)
    assert store.create_schedule(schedule).id == schedule.id
    assert store.get_schedule(schedule.id).can_activate
    assert "secret" not in database.read_bytes().decode("utf-8", errors="ignore").casefold()
    store.close()


def test_runner_is_idempotent_and_keeps_last_success_after_failure(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "state.sqlite3")
    store.create_schedule(definition(tmp_path, retention_limit=2))
    calls = 0

    def execute(schedule: ScheduleDefinition):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("source unavailable")
        return [PipelineArtifact(output="pdf", filename="report.pdf", content=f"run-{calls}".encode())]

    runner = LocalPipelineRunner(store, execute)
    first_time = datetime(2026, 8, 11, 12, tzinfo=timezone.utc)
    first = runner.run("schedule-1", scheduled_for=first_time)
    duplicate = runner.run("schedule-1", scheduled_for=first_time)
    assert first.status is RunStatus.SUCCEEDED
    assert duplicate.id == first.id
    second = runner.run("schedule-1", scheduled_for=first_time.replace(minute=1))
    failed = runner.run("schedule-1", scheduled_for=first_time.replace(minute=2))
    assert second.status is RunStatus.SUCCEEDED
    assert failed.status is RunStatus.FAILED
    assert (tmp_path / "reports" / "report.pdf").read_bytes() == b"run-2"
    assert len(store.successful_artifact_sets("schedule-1")) == 2
    assert len(store.list_artifacts(schedule_id="schedule-1")) == 2


def test_scheduler_http_endpoints_preview_and_approval_gate(tmp_path: Path, monkeypatch) -> None:
    import dashboard.api.schedules as schedules_api

    store = ScheduleStore(tmp_path / "api.sqlite3")
    monkeypatch.setattr(schedules_api, "schedule_store", store)
    schedules_api.configure_scheduler(runner=LocalPipelineRunner(store))
    from dashboard.api.main import app

    client = TestClient(app)
    payload = definition(
        tmp_path,
        enabled=False,
        project_non_confidential_confirmed=False,
        source_non_confidential_confirmed=False,
        approval_confirmed=False,
        approved_by=None,
    ).model_dump(mode="json")
    response = client.post("/api/schedules", json=payload)
    assert response.status_code == 201
    blocked = client.post(f"/api/schedules/{payload['id']}/activate", json={"approved_by": "owner"})
    assert blocked.status_code == 409
    preview = client.post("/api/schedules/preview", json={"schedule": payload, "count": 2})
    assert preview.status_code == 200
    assert len(preview.json()["occurrences"]) == 2
