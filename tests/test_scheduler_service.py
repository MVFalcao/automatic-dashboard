from datetime import datetime, timezone

from automation.scheduling.service import LocalSchedulerService
from test_scheduling import definition
from automation.scheduling.runner import LocalPipelineRunner
from automation.scheduling.store import ScheduleStore


def test_scheduler_tick_invokes_due_enabled_schedule(tmp_path):
    store = ScheduleStore(tmp_path / "state.sqlite3")
    schedule = definition(tmp_path, hour=9, minute=0)
    store.create_schedule(schedule)
    calls = []
    runner = LocalPipelineRunner(store, lambda schedule: calls.append(schedule.id) or [])
    service = LocalSchedulerService(store, runner, interval_seconds=60)
    service.tick(datetime(2026, 8, 11, 12, tzinfo=timezone.utc))
    assert calls == [schedule.id]
