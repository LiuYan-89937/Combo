from __future__ import annotations

from typing import Any

from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import bounded_int
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import (
    SYSTEM_CHAT_PACKAGE_ID,
)
from agent_factory.runtime_attachments import (
    AttachmentImportError,
    attachment_import_error_payload,
    redact_attachment_markers,
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
                ),
                request_id=command.request_id,
            )
            return
        if action == "create":
            job_payload = command.payload.get("job") if isinstance(command.payload.get("job"), dict) else command.payload
            job = runtime.create_job(dict(job_payload))
            self._emit_scheduler_job_snapshot("scheduler_job_created", job, status="created", request_id=command.request_id)
            return
        if action == "update":
            job_payload = command.payload.get("job") if isinstance(command.payload.get("job"), dict) else command.payload
            job = runtime.upsert_job(dict(job_payload))
            self._emit_scheduler_job_snapshot("scheduler_job_updated", job, status="updated", request_id=command.request_id)
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
                ),
                request_id=command.request_id,
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
                ),
                request_id=command.request_id,
            )
            return
        if action == "pause":
            if not job_id:
                self._emit_error(command, "scheduler pause requires job_id")
                return
            job = runtime.set_job_enabled(job_id, False)
            self._emit_scheduler_job_snapshot("scheduler_job_updated", job, status="paused", request_id=command.request_id)
            return
        if action == "resume":
            if not job_id:
                self._emit_error(command, "scheduler resume requires job_id")
                return
            job = runtime.set_job_enabled(job_id, True)
            self._emit_scheduler_job_snapshot("scheduler_job_updated", job, status="enabled", request_id=command.request_id)
            return
        if action == "delete":
            if not job_id:
                self._emit_error(command, "scheduler delete requires job_id")
                return
            deleted = runtime.delete_job(job_id)
            self._emit_scheduler_event(
                SchedulerEventPayload(
                    event_type="scheduler_job_deleted",
                    job_id=job_id,
                    owner_type=runtime.owner_type,
                    owner_id=runtime.owner_id,
                    status="deleted" if deleted else "missing",
                    payload={"deleted": deleted},
                ),
                request_id=command.request_id,
            )
            return
        if action == "run_now":
            if not job_id:
                self._emit_error(command, "scheduler run_now requires job_id")
                return
            runtime.run_now(job_id)
            return
        self._emit_error(command, f"unsupported scheduler action: {action}")

    def _emit_scheduler_job_snapshot(
        self,
        event_type: str,
        job: Any,
        *,
        status: str,
        request_id: str | None = None,
    ) -> None:
        self._emit_scheduler_event(
            SchedulerEventPayload(
                event_type=event_type,  # type: ignore[arg-type]
                job_id=job.job_id,
                owner_type=job.owner_type,
                owner_id=job.owner_id,
                target_type=job.target.target_type,
                status=status,
                payload={"job": job.model_dump(mode="json")},
            ),
            request_id=request_id,
        )

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

    def _emit_scheduler_event(self, payload: SchedulerEventPayload, *, request_id: str | None = None) -> None:
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=request_id,
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
        redacted_message = redact_attachment_markers(message)
        agent_session_id = self._planned_system_chat_agent_session_id()
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
            self._commit_system_chat_request(redacted_message)
            consume_result = self._consume_agent_package_stream(
                package_id=package_id,
                run=run,
                normalizer=normalizer,
                frontend_mode=mode,  # type: ignore[arg-type]
                frontend_session_id=self._session_id(),
            )
        except AttachmentImportError as exc:
            payload = attachment_import_error_payload(exc)
            normalizer.runtime_event(
                "run_failed",
                span_id=normalizer.run_span_id,
                severity="error",
                message=payload["message"],
                payload=payload,
            )
            return {"status": "failed", "error": payload["message"], "payload": payload}
        except Exception as exc:
            normalizer.emit_run_failed(exc)
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        if consume_result.status == "failed":
            return _scheduled_failure_result(consume_result, fallback="factory scheduled chat run failed")
        if consume_result.status == "interrupted":
            return {"status": "interrupted", "output_summary": f"factory scheduled {mode} run requested user input"}
        return {"status": "completed", "output_summary": f"factory scheduled {mode} run completed"}

    def _run_scheduled_create_agent(self, message: str) -> dict[str, Any]:
        redacted_message = redact_attachment_markers(message)
        agent_session_id = self._planned_host_create_agent_session_id()
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
            self._commit_host_create_agent_request(redacted_message, session_id=agent_session_id)
            consume_result = self._consume_create_agent_stream(run=run)
        except AttachmentImportError as exc:
            payload = attachment_import_error_payload(exc)
            normalizer.runtime_event(
                "run_failed",
                span_id=normalizer.run_span_id,
                severity="error",
                message=payload["message"],
                payload=payload,
            )
            return {"status": "failed", "error": payload["message"], "payload": payload}
        except Exception as exc:
            normalizer.emit_run_failed(exc)
            return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        if consume_result.status == "failed":
            return _scheduled_failure_result(consume_result, fallback="factory scheduled create-agent run failed")
        if consume_result.status == "interrupted" or self.pending_create_agent_run is not None:
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


def _scheduled_failure_result(result: Any, *, fallback: str) -> dict[str, Any]:
    terminal_event = getattr(result, "terminal_event", None)
    payload = getattr(terminal_event, "payload", None)
    payload = payload if isinstance(payload, dict) else {}
    message = str(
        payload.get("message")
        or getattr(terminal_event, "message", None)
        or getattr(result, "message", None)
        or fallback
    )
    return {"status": "failed", "error": message, "payload": payload}
