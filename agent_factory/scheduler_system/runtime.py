from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_factory.scheduler_system.config import default_factory_scheduler_config, factory_scheduler_owner_id
from agent_factory.scheduler_system.events import SchedulerEventPayload
from agent_factory.scheduler_system.executor import SchedulerExecutor
from agent_factory.scheduler_system.reports import SchedulerReportWriter
from agent_factory.scheduler_system.schema import (
    SchedulerContractConfig,
    SchedulerExecutionReport,
    SchedulerJob,
    SchedulerRun,
    utc_now,
)
from agent_factory.scheduler_system.store import SQLiteSchedulerStore


SchedulerEventSink = Callable[[SchedulerEventPayload], None]


class SchedulerRuntime:
    def __init__(
        self,
        *,
        config: SchedulerContractConfig,
        owner_type: str,
        owner_id: str,
        store: SQLiteSchedulerStore | None = None,
        executor: SchedulerExecutor | None = None,
        report_root: str | Path | None = None,
        event_sink: SchedulerEventSink | None = None,
    ) -> None:
        self.config = config
        self.owner_type = owner_type
        self.owner_id = owner_id
        self.store = store or SQLiteSchedulerStore(config.store_path)
        self.executor = executor or SchedulerExecutor()
        self.report_writer = SchedulerReportWriter(report_root or Path(config.store_path).with_suffix("") / "reports")
        self.event_sink = event_sink
        self.worker = None
        self.holder_id = f"{owner_type}:{owner_id}:{uuid4().hex}"

    def create_job(self, payload: dict[str, Any]) -> SchedulerJob:
        job = self._job_from_payload(payload)
        created = self.store.create_job(job)
        self.emit("scheduler_job_created", job=created, status="created")
        self.reschedule()
        return created

    def upsert_job(self, payload: dict[str, Any]) -> SchedulerJob:
        job = self._job_from_payload(payload)
        saved = self.store.upsert_job(job)
        self.emit("scheduler_job_updated", job=saved, status="updated")
        self.reschedule()
        return saved

    def list_jobs(self) -> list[SchedulerJob]:
        return self.store.list_jobs(owner_type=self.owner_type, owner_id=self.owner_id)

    def describe_job(self, job_id: str) -> dict[str, Any]:
        job = self._required_job(job_id)
        runs = self.store.list_runs(job_id=job_id, limit=10)
        return {
            "job": job.model_dump(mode="json"),
            "recent_runs": [item.model_dump(mode="json") for item in runs],
        }

    def set_job_enabled(self, job_id: str, enabled: bool) -> SchedulerJob:
        job = self._required_job(job_id)
        if job.owner_type != self.owner_type or job.owner_id != self.owner_id:
            raise PermissionError("scheduler job does not belong to current owner")
        saved = self.store.set_job_enabled(job_id, enabled)
        self.emit("scheduler_job_updated", job=saved, status="enabled" if enabled else "paused")
        self.reschedule()
        return saved

    def delete_job(self, job_id: str) -> bool:
        job = self._required_job(job_id)
        if job.owner_type != self.owner_type or job.owner_id != self.owner_id:
            raise PermissionError("scheduler job does not belong to current owner")
        deleted = self.store.delete_job(job_id)
        if deleted:
            self.emit("scheduler_job_deleted", job=job, status="deleted")
        self.reschedule()
        return deleted

    def run_now(self, job_id: str) -> SchedulerExecutionReport:
        job = self._required_job(job_id)
        return self.execute_job(job, trigger_reason="manual")

    def execute_job(self, job: SchedulerJob | str, *, trigger_reason: str = "scheduled") -> SchedulerExecutionReport:
        job = self._required_job(job) if isinstance(job, str) else job
        scheduled_at = utc_now().isoformat()
        run = SchedulerRun(
            job_id=job.job_id,
            owner_type=job.owner_type,
            owner_id=job.owner_id,
            target_type=job.target.target_type,
            status="pending",
            scheduled_at=scheduled_at,
            trigger_reason=trigger_reason,
        )
        self.store.create_run(run)
        self.emit("scheduler_run_scheduled", job=job, run=run)
        lease = self.store.acquire_lease(
            job_id=job.job_id,
            run_id=run.run_id,
            holder_id=self.holder_id,
            ttl_seconds=job.timeout_seconds,
        )
        if lease is None and job.concurrency_policy == "skip":
            skipped = run.model_copy(update={"status": "skipped", "completed_at": utc_now().isoformat()})
            self.store.update_run(skipped)
            report = SchedulerExecutionReport(
                run_id=run.run_id,
                job_id=job.job_id,
                owner_type=job.owner_type,
                owner_id=job.owner_id,
                target_type=job.target.target_type,
                status="skipped",
                started_at=scheduled_at,
                completed_at=skipped.completed_at or scheduled_at,
                duration_ms=0,
                error_summary="another run is already active",
            )
            report_path = self.report_writer.write(report)
            self.emit("scheduler_run_skipped", job=job, run=skipped, report=report, report_path=report_path)
            return report
        if lease is None:
            raise RuntimeError(f"scheduler job is already leased: {job.job_id}")
        running = run.model_copy(update={"status": "running", "started_at": utc_now().isoformat()})
        self.store.update_run(running)
        self.emit("scheduler_run_started", job=job, run=running)
        try:
            report = self.executor.execute(job=job, run=running)
            report_path = self.report_writer.write(report)
            status = "completed" if report.status == "completed" else "failed"
            completed = running.model_copy(
                update={
                    "status": status,
                    "completed_at": report.completed_at,
                    "output_summary": report.output_summary,
                    "error_summary": report.error_summary,
                    "report_path": report_path,
                }
            )
            self.store.update_run(completed)
            self.emit(
                "scheduler_run_completed" if status == "completed" else "scheduler_run_failed",
                job=job,
                run=completed,
                report=report,
                report_path=report_path,
            )
            return report.model_copy(update={"evidence": {**report.evidence, "report_path": report_path}})
        finally:
            self.store.release_lease(job_id=job.job_id, run_id=run.run_id)

    def reschedule(self) -> None:
        worker = self.worker
        if worker is not None:
            worker.reload_jobs()

    def emit(
        self,
        event_type: str,
        *,
        job: SchedulerJob | None = None,
        run: SchedulerRun | None = None,
        status: str | None = None,
        report: SchedulerExecutionReport | None = None,
        report_path: str | None = None,
    ) -> None:
        if self.event_sink is None:
            return
        duration_ms = report.duration_ms if report is not None else None
        payload = SchedulerEventPayload(
            event_type=event_type,  # type: ignore[arg-type]
            job_id=job.job_id if job else run.job_id if run else None,
            run_id=run.run_id if run else report.run_id if report else None,
            owner_type=job.owner_type if job else run.owner_type if run else self.owner_type,
            owner_id=job.owner_id if job else run.owner_id if run else self.owner_id,
            target_type=job.target.target_type if job else run.target_type if run else None,
            status=status or (run.status if run else report.status if report else None),
            scheduled_at=run.scheduled_at if run else None,
            duration_ms=duration_ms,
            error_summary=report.error_summary if report else run.error_summary if run else None,
            report_path=report_path,
        )
        self.event_sink(payload)

    def _job_from_payload(self, payload: dict[str, Any]) -> SchedulerJob:
        job_payload = {
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "timezone": self.config.timezone,
            "concurrency_policy": self.config.default_concurrency_policy,
            "timeout_seconds": self.config.default_timeout_seconds,
            "unattended_policy": self.config.unattended_policy,
            **payload,
        }
        return SchedulerJob.model_validate(job_payload)

    def _required_job(self, job_id: str) -> SchedulerJob:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(f"unknown scheduler job: {job_id}")
        return job


def default_factory_scheduler_runtime(*, event_sink: SchedulerEventSink | None = None) -> SchedulerRuntime:
    return SchedulerRuntime(
        config=default_factory_scheduler_config(),
        owner_type="factory",
        owner_id=factory_scheduler_owner_id(),
        event_sink=event_sink,
    )
