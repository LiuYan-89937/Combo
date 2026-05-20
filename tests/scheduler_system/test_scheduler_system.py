from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from agent_factory.scheduler_system import (
    SchedulerContractConfig,
    SchedulerExecutor,
    SchedulerRuntime,
    SQLiteSchedulerStore,
    deny_if_unattended_approval_required,
)
from agent_factory.scheduler_system.schema import SchedulerJob


class SchedulerSystemTest(unittest.TestCase):
    def test_job_schema_rejects_invalid_cron(self) -> None:
        with self.assertRaises(ValueError):
            SchedulerJob(
                owner_type="factory",
                owner_id="default",
                schedule_type="cron",
                schedule_expr="not a cron",
                target={"target_type": "graph_run", "payload": {"message": "hello"}},
            )

    def test_sqlite_store_crud_and_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteSchedulerStore(Path(temp_dir) / "scheduler.sqlite")
            job = store.create_job(_job())
            self.assertEqual(store.get_job(job.job_id).job_id, job.job_id)  # type: ignore[union-attr]
            self.assertEqual(len(store.list_jobs(owner_type="factory", owner_id="default")), 1)
            paused = store.set_job_enabled(job.job_id, False)
            self.assertFalse(paused.enabled)
            self.assertTrue(store.delete_job(job.job_id))

    def test_lease_prevents_duplicate_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteSchedulerStore(Path(temp_dir) / "scheduler.sqlite")
            job = store.create_job(_job())
            lease = store.acquire_lease(job_id=job.job_id, run_id="run_1", holder_id="holder", ttl_seconds=60)
            self.assertIsNotNone(lease)
            self.assertIsNone(store.acquire_lease(job_id=job.job_id, run_id="run_2", holder_id="holder", ttl_seconds=60))
            store.release_lease(job_id=job.job_id, run_id="run_1")
            self.assertIsNotNone(store.acquire_lease(job_id=job.job_id, run_id="run_3", holder_id="holder", ttl_seconds=60))

    def test_script_run_uses_tool_runner(self) -> None:
        calls = []

        def tool_runner(tool_id, arguments, _job, _run):
            calls.append((tool_id, arguments))
            return {"status": "completed", "stdout": "ok"}

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = SchedulerRuntime(
                config=SchedulerContractConfig(store_path=str(Path(temp_dir) / "scheduler.sqlite")),
                owner_type="factory",
                owner_id="default",
                executor=SchedulerExecutor(tool_runner=tool_runner),
            )
            job = runtime.create_job(
                {
                    "schedule_type": "interval",
                    "schedule_expr": "60",
                    "target": {"target_type": "script_run", "payload": {"command": ["echo", "ok"]}},
                }
            )
            report = runtime.run_now(job.job_id)

            self.assertEqual(report.status, "completed")
            self.assertEqual(calls[0][0], "bash")
            self.assertEqual(calls[0][1]["command"], ["echo", "ok"])

    def test_unconfigured_high_level_target_fails_as_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = SchedulerRuntime(
                config=SchedulerContractConfig(store_path=str(Path(temp_dir) / "scheduler.sqlite")),
                owner_type="agent",
                owner_id="agent_1",
            )
            job = runtime.create_job(
                {
                    "schedule_type": "interval",
                    "schedule_expr": "60",
                    "target": {"target_type": "graph_run", "payload": {"message": "hello"}},
                }
            )
            report = runtime.run_now(job.job_id)

            self.assertEqual(report.status, "failed")
            self.assertIn("graph_run target is not configured", report.error_summary or "")

    def test_unattended_policy_denies_approval_required_tool(self) -> None:
        job = _job().model_copy(
            update={
                "target": {"target_type": "tool_call", "payload": {"tool_id": "bash", "arguments": {}}},
                "unattended_policy": "deny_if_approval_required",
            }
        )
        tool = _FakeModelTool(risk_level="high")

        result = deny_if_unattended_approval_required(job=job, tool_id="bash", model_tool=tool)

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "failed")  # type: ignore[index]
        self.assertIn("approval-required", result["error"])  # type: ignore[index]


def _job() -> SchedulerJob:
    return SchedulerJob(
        owner_type="factory",
        owner_id="default",
        schedule_type="cron",
        schedule_expr="0 9 * * *",
        target={"target_type": "graph_run", "payload": {"message": "daily report"}},
    )


class _FakeModelTool:
    def __init__(self, *, risk_level: str) -> None:
        self.metadata = {"agent_factory": {"risk_level": risk_level}}
