from __future__ import annotations

from typing import Any

from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import bounded_int
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import (
    SYSTEM_CHAT_PACKAGE_ID,
)
from agent_factory.runtime_kernel.background_workers import RuntimeBackgroundWorkerManager, WorkerLifecycleEvent
from agent_factory.scheduler_system import (
    SchedulerExecutor,
    SchedulerWorker,
    default_factory_scheduler_runtime,
    scheduler_tool_approval_override,
)
from agent_factory.scheduler_system.events import SchedulerEventPayload
from agent_factory.tooling import get_factory_tools


class RuntimeSchedulerCommandMixin:
    def scheduler_manage(self, command: FactoryFrontendCommand) -> None:
        runtime = self.scheduler_runtime
        if runtime is None:
            self._emit_error(command, "scheduler runtime is not enabled")
            return
        action = str(command.payload.get("action") or "list").strip()
        job_id = str(command.payload.get("job_id") or "").strip()
        limit = bounded_int(command.payload.get("limit"), default=20, minimum=1, maximum=200)
        if action == "list":
            jobs = runtime.list_jobs()
            self._emit_scheduler_event(
                SchedulerEventPayload(
                    event_type="scheduler_jobs_listed",
                    owner_type=runtime.owner_type,
                    owner_id=runtime.owner_id,
                    status="listed",
                    payload={"jobs": [job.model_dump(mode="json") for job in jobs], "count": len(jobs)},
                )
            )
            return
        if action == "describe":
            if not job_id:
                self._emit_error(command, "scheduler describe requires job_id")
                return
            description = runtime.describe_job(job_id)
            job_payload = description.get("job") if isinstance(description.get("job"), dict) else {}
            target_payload = job_payload.get("target", {}) if isinstance(job_payload, dict) else {}
            self._emit_scheduler_event(
                SchedulerEventPayload(
                    event_type="scheduler_job_described",
                    job_id=job_id,
                    owner_type=runtime.owner_type,
                    owner_id=runtime.owner_id,
                    target_type=target_payload.get("target_type") if isinstance(target_payload, dict) else None,
                    status="described",
                    payload=description,
                )
            )
            return
        if action == "runs":
            runs = runtime.store.list_runs(job_id=job_id or None, limit=limit)
            self._emit_scheduler_event(
                SchedulerEventPayload(
                    event_type="scheduler_runs_listed",
                    job_id=job_id or None,
                    owner_type=runtime.owner_type,
                    owner_id=runtime.owner_id,
                    status="listed",
                    payload={"runs": [run.model_dump(mode="json") for run in runs], "count": len(runs), "limit": limit},
                )
            )
            return
        if action == "pause":
            if not job_id:
                self._emit_error(command, "scheduler pause requires job_id")
                return
            runtime.set_job_enabled(job_id, False)
            return
        if action == "resume":
            if not job_id:
                self._emit_error(command, "scheduler resume requires job_id")
                return
            runtime.set_job_enabled(job_id, True)
            return
        if action == "delete":
            if not job_id:
                self._emit_error(command, "scheduler delete requires job_id")
                return
            runtime.delete_job(job_id)
            return
        if action == "run_now":
            if not job_id:
                self._emit_error(command, "scheduler run_now requires job_id")
                return
            runtime.run_now(job_id)
            return
        self._emit_error(command, f"unsupported scheduler action: {action}")

    def _start_factory_scheduler(self) -> None:
        runtime = default_factory_scheduler_runtime(event_sink=self._emit_scheduler_event)
        runtime.executor = SchedulerExecutor(
            graph_runner=self._scheduler_graph_runner,
            tool_runner=self._scheduler_tool_runner,
        )
        worker = SchedulerWorker(runtime)
        if self.background_workers is None:
            self.background_workers = RuntimeBackgroundWorkerManager()
        self.background_workers.add(worker)
        self.scheduler_runtime = runtime
        for lifecycle_event in self.background_workers.start_all():
            if lifecycle_event.status == "failed":
                self._emit_worker_lifecycle_failure(lifecycle_event)

    def _shutdown_background_workers(self) -> None:
        if self.background_workers is None:
            return
        for lifecycle_event in self.background_workers.shutdown_all():
            if lifecycle_event.status == "failed":
                self._emit_worker_lifecycle_failure(lifecycle_event)

    def _emit_worker_lifecycle_failure(self, lifecycle_event: WorkerLifecycleEvent) -> None:
        self._emit_scheduler_event(
            SchedulerEventPayload(
                event_type="scheduler_run_failed",
                owner_type="factory",
                owner_id="default",
                status="failed",
                error_summary=(
                    f"background worker {lifecycle_event.action} failed: "
                    f"{lifecycle_event.worker_id}: {lifecycle_event.message}"
                ),
            )
        )

    def _emit_scheduler_event(self, payload: SchedulerEventPayload) -> None:
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=None,
            session_id=self._session_id(),
            mode=self.mode,
            graph_id="factory_scheduler",
            producer_type="factory_runtime",
        )
        normalizer.emit_custom_event({"type": "scheduler_event", "payload": payload.model_dump(mode="json")})

    def _scheduler_tool_runner(self, tool_id: str, arguments: dict[str, Any], job: Any, _run: Any) -> dict[str, Any]:
        tools = {tool.name: tool for tool in self._factory_tools()}
        tool = tools.get(tool_id)
        if tool is None:
            return {"status": "failed", "error": f"unknown factory tool: {tool_id}"}
        with scheduler_tool_approval_override(job=job, tool_id=tool_id):
            result = tool.invoke(arguments)
        if isinstance(result, dict):
            return result
        return {"status": "completed", "value": result}

    def _scheduler_graph_runner(self, job: Any, _run: Any) -> dict[str, Any]:
        payload = dict(job.target.payload)
        message = str(payload.get("message") or "").strip()
        mode = str(payload.get("mode") or "chat")
        if mode not in {"chat", "create_agent"}:
            return {"status": "failed", "error": f"unsupported factory scheduler graph mode: {mode}"}
        self._ensure_session(FactoryFrontendCommand(type="start_session"))
        if mode == "create_agent":
            return self._run_scheduled_create_agent(message)
        package_id = SYSTEM_CHAT_PACKAGE_ID
        agent_session_id = self._ensure_system_chat_agent_session(message)
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=None,
            session_id=self._session_id(),
            mode="chat",
            graph_id=f"factory_{mode}_package_scheduler",
            producer_type="factory_runtime",
        )
        try:
            run = self.agent_package_runtime.stream(
                package_id,
                user_input=message,
                session_id=agent_session_id,
                request_id=None,
            )
            self._consume_agent_package_stream(
                package_id=package_id,
                run=run,
                normalizer=normalizer,
                frontend_mode=mode,  # type: ignore[arg-type]
                frontend_session_id=self._session_id(),
            )
        except Exception as exc:
            normalizer.emit_run_failed(exc)
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        return {"status": "completed", "output_summary": f"factory scheduled {mode} run completed"}

    def _run_scheduled_create_agent(self, message: str) -> dict[str, Any]:
        agent_session_id = self._ensure_host_create_agent_session(message)
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=None,
            session_id=self._session_id(),
            mode="create_agent",
            graph_id="create_agent_react_scheduler",
            producer_type="factory_runtime",
        )
        try:
            run = self.create_agent_runtime.stream(
                user_input=message,
                session_id=agent_session_id,
                request_id=None,
            )
            self._consume_create_agent_stream(run=run)
        except Exception as exc:
            normalizer.emit_run_failed(exc)
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        if self.pending_create_agent_run is not None:
            return {"status": "interrupted", "output_summary": "scheduled create-agent run requested user input"}
        return {"status": "completed", "output_summary": "factory scheduled create_agent run completed"}

    def _factory_tools(self, tool_ids: list[str] | set[str] | tuple[str, ...] | None = None) -> list[Any]:
        return get_factory_tools(
            tool_ids=tool_ids,
            tool_runtime_resources=self._factory_tool_runtime_resources(),
        )

    def _factory_tool_runtime_resources(self) -> dict[str, Any]:
        if self.scheduler_runtime is None:
            return {}
        return {"scheduler_runtime": self.scheduler_runtime}
