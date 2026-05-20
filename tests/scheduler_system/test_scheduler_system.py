from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from agent_factory.scheduler_system import (
    SchedulerContractConfig,
    SchedulerExecutor,
    SchedulerFeedbackSummaryDecision,
    SchedulerRuntime,
    SQLiteSchedulerStore,
)
from agent_factory.scheduler_system.schema import SchedulerJob
from agent_factory.scheduler_system.executor import runtime_tool_runner
from agent_factory.tooling.gateway import ToolApprovalDecision, ToolExecutionGateway
from agent_factory.tooling.schema_compiler import compile_json_schema
from agent_factory.tooling.spec import ToolSpec


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
                    "target": {
                        "target_type": "script_run",
                        "payload": {
                            "command": "echo ok",
                            "mode": "foreground",
                            "wait_seconds": 3,
                            "max_output_chars": 2000,
                        },
                    },
                }
            )
            report = runtime.run_now(job.job_id)

            self.assertEqual(report.status, "completed")
            self.assertEqual(calls[0][0], "bash")
            self.assertEqual(calls[0][1]["command"], "echo ok")
            self.assertEqual(calls[0][1]["mode"], "foreground")
            self.assertEqual(calls[0][1]["wait_seconds"], 3)
            self.assertEqual(calls[0][1]["max_output_chars"], 2000)

    def test_completed_run_emits_structured_feedback_event(self) -> None:
        events = []

        def tool_runner(_tool_id, _arguments, _job, _run):
            return {"status": "completed", "stdout": "天气晴朗"}

        def summarizer(*, job, run, report, completed_count):
            self.assertEqual(job.task_content, "每一分钟汇报随机一个城市的天气")
            self.assertEqual(report.status, "completed")
            self.assertEqual(completed_count, 1)
            return SchedulerFeedbackSummaryDecision(summary="本次定时任务已完成，脚本输出显示天气晴朗。")

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = SchedulerRuntime(
                config=SchedulerContractConfig(store_path=str(Path(temp_dir) / "scheduler.sqlite")),
                owner_type="factory",
                owner_id="default",
                executor=SchedulerExecutor(tool_runner=tool_runner),
                event_sink=events.append,
                feedback_summarizer=summarizer,
            )
            job = runtime.create_job(
                {
                    "job_id": "weather_job",
                    "task_content": "每一分钟汇报随机一个城市的天气",
                    "schedule_type": "interval",
                    "schedule_expr": "60",
                    "target": {"target_type": "script_run", "payload": {"command": "echo ok"}},
                }
            )
            runtime.run_now(job.job_id)

        feedback_events = [event for event in events if event.event_type == "scheduler_feedback_completed"]
        self.assertEqual(len(feedback_events), 1)
        self.assertEqual(feedback_events[0].job_id, "weather_job")
        self.assertEqual(feedback_events[0].completed_count, 1)
        self.assertEqual(feedback_events[0].task_content, "每一分钟汇报随机一个城市的天气")
        self.assertEqual(feedback_events[0].summary, "本次定时任务已完成，脚本输出显示天气晴朗。")

    def test_gateway_style_tool_output_is_lifted_to_scheduler_report(self) -> None:
        def tool_runner(_tool_id, _arguments, _job, _run):
            return {
                "status": "completed",
                "message": "Tool execution completed.",
                "output": {
                    "stdout": "bangkok: rainy +32C",
                    "stderr": "",
                    "exit_code": 0,
                },
            }

        def summarizer(*, job, run, report, completed_count):
            self.assertEqual(report.output_summary, "bangkok: rainy +32C")
            self.assertEqual(report.stdout_preview, "bangkok: rainy +32C")
            self.assertEqual(report.stderr_preview, None)
            self.assertEqual(report.exit_code, 0)
            return SchedulerFeedbackSummaryDecision(summary=f"第 {completed_count} 次完成：bangkok: rainy +32C")

        with tempfile.TemporaryDirectory() as temp_dir:
            events = []
            runtime = SchedulerRuntime(
                config=SchedulerContractConfig(store_path=str(Path(temp_dir) / "scheduler.sqlite")),
                owner_type="factory",
                owner_id="default",
                executor=SchedulerExecutor(tool_runner=tool_runner),
                event_sink=events.append,
                feedback_summarizer=summarizer,
            )
            job = runtime.create_job(
                {
                    "job_id": "gateway_style_weather",
                    "task_content": "每分钟随机查询天气",
                    "schedule_type": "interval",
                    "schedule_expr": "60",
                    "target": {"target_type": "script_run", "payload": {"command": "echo weather"}},
                }
            )
            report = runtime.run_now(job.job_id)

        self.assertEqual(report.output_summary, "bangkok: rainy +32C")
        self.assertEqual(report.stdout_preview, "bangkok: rainy +32C")
        self.assertEqual(report.exit_code, 0)

    def test_gateway_style_failed_tool_stderr_is_lifted_to_error_summary(self) -> None:
        def tool_runner(_tool_id, _arguments, _job, _run):
            return {
                "status": "failed",
                "message": "Tool execution failed.",
                "output": {
                    "stdout": "",
                    "stderr": "permission denied",
                    "exit_code": 126,
                },
            }

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
                    "target": {"target_type": "script_run", "payload": {"command": "echo weather"}},
                }
            )
            report = runtime.run_now(job.job_id)

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.stderr_preview, "permission denied")
        self.assertEqual(report.error_summary, "permission denied")
        self.assertEqual(report.exit_code, 126)

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

    def test_job_auto_pauses_after_consecutive_failures(self) -> None:
        events = []

        def tool_runner(_tool_id, _arguments, _job, _run):
            return {"status": "failed", "output": {"stderr": "boom", "exit_code": 1}}

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = SchedulerRuntime(
                config=SchedulerContractConfig(store_path=str(Path(temp_dir) / "scheduler.sqlite")),
                owner_type="factory",
                owner_id="default",
                executor=SchedulerExecutor(tool_runner=tool_runner),
                event_sink=events.append,
            )
            job = runtime.create_job(
                {
                    "schedule_type": "interval",
                    "schedule_expr": "60",
                    "failure_policy": {"enabled": True, "max_consecutive_failures": 2, "action": "pause"},
                    "target": {"target_type": "script_run", "payload": {"command": "echo fail"}},
                }
            )

            runtime.run_now(job.job_id)
            self.assertTrue(runtime.store.get_job(job.job_id).enabled)  # type: ignore[union-attr]
            runtime.run_now(job.job_id)

            saved = runtime.store.get_job(job.job_id)
            self.assertIsNotNone(saved)
            self.assertFalse(saved.enabled)  # type: ignore[union-attr]
            auto_paused = [event for event in events if event.event_type == "scheduler_job_auto_paused"]
            self.assertEqual(len(auto_paused), 1)
            self.assertEqual(auto_paused[0].payload["consecutive_failures"], 2)
            self.assertEqual(auto_paused[0].payload["threshold"], 2)

    def test_success_breaks_consecutive_failure_auto_pause_count(self) -> None:
        outcomes = iter([
            {"status": "failed", "output": {"stderr": "first failure", "exit_code": 1}},
            {"status": "completed", "stdout": "ok"},
            {"status": "failed", "output": {"stderr": "second failure", "exit_code": 1}},
        ])

        def tool_runner(_tool_id, _arguments, _job, _run):
            return next(outcomes)

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
                    "failure_policy": {"enabled": True, "max_consecutive_failures": 2, "action": "pause"},
                    "target": {"target_type": "script_run", "payload": {"command": "echo sometimes"}},
                }
            )

            runtime.run_now(job.job_id)
            runtime.run_now(job.job_id)
            runtime.run_now(job.job_id)

            saved = runtime.store.get_job(job.job_id)
            self.assertIsNotNone(saved)
            self.assertTrue(saved.enabled)  # type: ignore[union-attr]

    def test_scheduler_tool_runner_skips_human_approval_interrupt_only(self) -> None:
        entrypoint_calls = []
        approval_calls = []
        spec = ToolSpec(
            id="high_risk_tool",
            description="High risk test tool.",
            entrypoint="test:run",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
            resources={},
            risk_level="high",
        )
        gateway = ToolExecutionGateway(
            spec=spec,
            input_schema=compile_json_schema(schema=spec.input_schema, model_name="SchedulerHighRiskArgs"),
            output_schema=compile_json_schema(schema=spec.output_schema, model_name="SchedulerHighRiskOutput"),
            entrypoint=lambda arguments, resources: entrypoint_calls.append((arguments, resources)) or {"ok": True},
            global_resources={},
            approval_handler=lambda _spec, _arguments, _risk: approval_calls.append(True) or ToolApprovalDecision(action="deny"),
        )
        registry = _FakeRegistry(gateway)
        job = _job_with_target(
            {
                "target_type": "tool_call",
                "payload": {"tool_id": "high_risk_tool", "arguments": {"value": "ok"}},
            },
            unattended_policy="deny_if_approval_required",
        )
        run = _run_for_job(job)

        result = runtime_tool_runner(registry)("high_risk_tool", {"value": "ok"}, job, run)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(entrypoint_calls[0][0], {"value": "ok"})
        self.assertEqual(approval_calls, [])

    def test_scheduler_tool_runner_still_uses_gateway_schema_validation(self) -> None:
        entrypoint_calls = []
        spec = ToolSpec(
            id="schema_checked_tool",
            description="Schema checked test tool.",
            entrypoint="test:run",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            output_schema={"type": "object", "additionalProperties": True},
            resources={},
            risk_level="high",
        )
        gateway = ToolExecutionGateway(
            spec=spec,
            input_schema=compile_json_schema(schema=spec.input_schema, model_name="SchedulerSchemaArgs"),
            output_schema=compile_json_schema(schema=spec.output_schema, model_name="SchedulerSchemaOutput"),
            entrypoint=lambda arguments, resources: entrypoint_calls.append((arguments, resources)) or {"ok": True},
            global_resources={},
        )
        registry = _FakeRegistry(gateway)
        job = _job_with_target(
            {
                "target_type": "tool_call",
                "payload": {"tool_id": "schema_checked_tool", "arguments": {}},
            }
        )
        run = _run_for_job(job)

        result = runtime_tool_runner(registry)("schema_checked_tool", {}, job, run)

        self.assertEqual(result["status"], "invalid_arguments")
        self.assertIn("schema validation", result["error"])
        self.assertEqual(entrypoint_calls, [])


def _job() -> SchedulerJob:
    return SchedulerJob(
        owner_type="factory",
        owner_id="default",
        schedule_type="cron",
        schedule_expr="0 9 * * *",
        target={"target_type": "graph_run", "payload": {"message": "daily report"}},
    )


def _job_with_target(target: dict, **updates) -> SchedulerJob:
    payload = _job().model_dump(mode="json")
    payload.update(updates)
    payload["target"] = target
    return SchedulerJob.model_validate(payload)


def _run_for_job(job: SchedulerJob):
    from agent_factory.scheduler_system.schema import SchedulerRun, utc_now

    return SchedulerRun(
        job_id=job.job_id,
        owner_type=job.owner_type,
        owner_id=job.owner_id,
        target_type=job.target.target_type,
        scheduled_at=utc_now().isoformat(),
    )


class _FakeRegistry:
    def __init__(self, gateway: ToolExecutionGateway) -> None:
        self.gateway = gateway

    def execute(self, _tool_id: str, arguments: dict, *, state) -> object:
        from agent_factory.runtime_kernel.types import ToolExecutionResult

        del state
        output = self.gateway.execute(arguments)
        status = "completed" if output.get("status") == "completed" else "failed"
        return ToolExecutionResult(
            status=status,
            output=output,
            error=output.get("message") if status == "failed" else None,
            observation_summary=output.get("message"),
        )
