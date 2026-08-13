from automation.scheduling.service import LocalSchedulerService
from test_scheduling import definition
from automation.scheduling.runner import LocalPipelineRunner
from automation.scheduling.store import ScheduleStore


class Jobs:
    def __init__(self):
        self.jobs = {}
        self.created = 0
        self.updated = 0
        self.deleted = []

    def list_jobs(self):
        return list(self.jobs.values())

    def create_job(self, payload):
        self.created += 1
        result = {**payload, "id": f"job-{self.created}"}
        self.jobs[result["id"]] = result
        return result

    def update_job(self, job_id, payload):
        self.updated += 1
        self.jobs[job_id] = {**payload, "id": job_id}
        return self.jobs[job_id]

    def delete_job(self, job_id):
        self.deleted.append(job_id)
        self.jobs.pop(job_id, None)


def test_scheduler_reconciles_one_managed_hermes_job_and_never_ticks_independently(tmp_path):
    store = ScheduleStore(tmp_path / "state.sqlite3")
    schedule = definition(tmp_path, hour=9, minute=0)
    store.create_schedule(schedule)
    calls = []
    runner = LocalPipelineRunner(store, lambda schedule: calls.append(schedule.id) or [])
    service = LocalSchedulerService(store, runner, interval_seconds=60)
    jobs = Jobs()
    service.set_gateway_client(jobs, script_directory=tmp_path / "hermes" / "scripts")
    service.start()
    assert jobs.created == 1
    assert store.get_binding(schedule.id)[0] == "job-1"
    assert (tmp_path / "hermes" / "scripts" / f"dashboard-{schedule.id}.py").exists()
    assert jobs.jobs["job-1"]["no_agent"] is True
    service.tick()
    assert jobs.created == 1
    assert calls == []

    store.update_schedule(schedule.model_copy(update={"minute": 5}))
    service.tick()
    assert jobs.updated == 1
    store.update_schedule(schedule.model_copy(update={"enabled": False}))
    service.tick()
    assert jobs.deleted == ["job-1"]
