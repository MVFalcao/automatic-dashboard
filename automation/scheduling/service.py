"""Persistent-process local scheduler ticker."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Thread

from automation.scheduling.cron import preview_schedule
from automation.scheduling.runner import LocalPipelineRunner
from automation.scheduling.store import ScheduleStore


class LocalSchedulerService:
    def __init__(self, store: ScheduleStore, runner: LocalPipelineRunner, interval_seconds: float = 30.0) -> None:
        self.store = store
        self.runner = runner
        self.interval_seconds = interval_seconds
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="dashboard-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def tick(self, now: datetime | None = None) -> None:
        instant = now or datetime.now(timezone.utc)
        for schedule in self.store.list_schedules():
            if not schedule.enabled:
                continue
            from datetime import timedelta
            occurrences = preview_schedule(schedule, after=instant - timedelta(seconds=self.interval_seconds), count=1)
            if occurrences and abs((occurrences[0] - instant).total_seconds()) < self.interval_seconds:
                self.runner.run(schedule.id, scheduled_for=occurrences[0])

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.tick()
