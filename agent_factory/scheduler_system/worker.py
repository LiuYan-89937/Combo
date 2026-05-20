from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler

from agent_factory.scheduler_system.runtime import SchedulerRuntime
from agent_factory.scheduler_system.triggers import build_trigger


class SchedulerWorker:
    def __init__(self, runtime: SchedulerRuntime) -> None:
        self.runtime = runtime
        self.scheduler = BackgroundScheduler(timezone=runtime.config.timezone)
        self.runtime.worker = self
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.reload_jobs()
        self.scheduler.start(paused=False)
        self._started = True

    def reload_jobs(self) -> None:
        for job in list(self.scheduler.get_jobs()):
            self.scheduler.remove_job(job.id)
        for job in self.runtime.list_jobs():
            if not job.enabled:
                continue
            self.scheduler.add_job(
                self._execute_job,
                trigger=build_trigger(
                    schedule_type=job.schedule_type,
                    schedule_expr=job.schedule_expr,
                    timezone=job.timezone,
                ),
                id=job.job_id,
                args=[job.job_id],
                replace_existing=True,
                coalesce=True,
                max_instances=job.max_concurrent_runs,
                misfire_grace_time=job.timeout_seconds,
            )

    def shutdown(self) -> None:
        if not self._started:
            return
        self.scheduler.shutdown(wait=False)
        self._started = False

    def _execute_job(self, job_id: str) -> None:
        self.runtime.execute_job(job_id, trigger_reason="scheduled")
