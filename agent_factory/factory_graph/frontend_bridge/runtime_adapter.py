from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.factory_package.constants import DEFAULT_CREATE_AGENT_BREAKPOINT_STAGE, STAGE_IDS
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer, json_safe
from agent_factory.factory_graph.frontend_bridge.protocol import (
    FactoryFrontendCommand,
    FactoryFrontendEvent,
    FactoryMode,
    event,
)
from agent_factory.factory_graph.session import (
    FactorySessionManager,
)
from agent_factory.memory_system.factory import shutdown_factory_memory_worker
from agent_factory.runtime_kernel.background_workers import RuntimeBackgroundWorkerManager, WorkerLifecycleEvent
from agent_factory.runtime_protocol.completion import runtime_completed, runtime_error_message
from agent_factory.scheduler_system import (
    SchedulerExecutor,
    SchedulerRuntime,
    SchedulerWorker,
    default_factory_scheduler_runtime,
    scheduler_enabled_from_env,
    scheduler_tool_approval_override,
)
from agent_factory.scheduler_system.events import SchedulerEventPayload
from agent_factory.tooling import get_factory_base_tool_ids
from agent_factory.tooling import get_factory_tools


Emit = Callable[[FactoryFrontendEvent], None]
SYSTEM_CHAT_PACKAGE_ID = "factory_chat"
SYSTEM_CREATE_AGENT_PACKAGE_ID = "factory_create_agent"


@dataclass(slots=True)
class FactoryBridgeOptions:
    stop_after_stage: str | None = DEFAULT_CREATE_AGENT_BREAKPOINT_STAGE
    show_state: bool = False
    show_messages: bool = True


@dataclass(slots=True)
class PendingAgentPackageRun:
    package_id: str
    session_id: str
    normalizer: RuntimeEventNormalizer


@dataclass(slots=True)
class FactoryRuntimeAdapter:
    emit: Emit
    session_manager: FactorySessionManager | None = None
    checkpointer: Any = None
    checkpointer_handle: Any = None
    options: FactoryBridgeOptions = field(default_factory=FactoryBridgeOptions)
    session_record: Any | None = None
    mode: FactoryMode | None = None
    pending_agent_package_run: PendingAgentPackageRun | None = None
    agent_package_runtime: AgentPackageRuntimeManager | None = None
    scheduler_runtime: SchedulerRuntime | None = None
    background_workers: RuntimeBackgroundWorkerManager | None = None

    def __post_init__(self) -> None:
        load_agentfactory_dotenv()
        if self.session_manager is None:
            self.session_manager = FactorySessionManager.from_env()
        if self.agent_package_runtime is None:
            self.agent_package_runtime = AgentPackageRuntimeManager()
        self.agent_package_runtime.set_emit(self.emit)
        if scheduler_enabled_from_env():
            self._start_factory_scheduler()

    def handle(self, command: FactoryFrontendCommand) -> bool:
        try:
            if command.type == "shutdown":
                if self.agent_package_runtime is not None:
                    self.agent_package_runtime.close_all()
                self._shutdown_background_workers()
                shutdown_factory_memory_worker()
                return False
            if command.type == "start_session":
                self.start_session(command)
            elif command.type == "list_sessions":
                self.list_sessions(command)
            elif command.type == "switch_session":
                self.switch_session(command)
            elif command.type == "new_session":
                self.new_session(command)
            elif command.type == "set_mode":
                self.set_mode(command)
            elif command.type == "set_options":
                self.set_options(command)
            elif command.type == "send_message":
                self.send_message(command)
            elif command.type == "rerun_from_stage":
                self.rerun_from_stage(command)
            elif command.type == "scheduler_manage":
                self.scheduler_manage(command)
            elif command.type == "list_agent_packages":
                self.list_agent_packages(command)
            elif command.type == "select_agent_package":
                self.select_agent_package(command)
            elif command.type == "delete_agent_package":
                self.delete_agent_package(command)
            elif command.type == "list_agent_package_sessions":
                self.list_agent_package_sessions(command)
            elif command.type == "run_agent_package":
                self.run_agent_package(command)
            elif command.type == "resume_interrupt":
                self.resume_interrupt(command)
            elif command.type == "cancel_runtime_request":
                self.cancel_runtime_request(command)
            else:
                self._emit_error(command, f"unsupported command: {command.type}")
        except Exception as exc:
            self.emit(
                event(
                    "error",
                    request_id=command.request_id,
                    session_id=self._session_id(),
                    mode=self.mode,
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
        return True

    def start_session(self, command: FactoryFrontendCommand) -> None:
        if command.session_id:
            self.session_record = self.session_manager.load(command.session_id)
            session_event_type = "session_switched"
        elif command.resume_latest:
            self.session_record = self.session_manager.latest() or self.session_manager.create()
            session_event_type = "session_switched" if self.session_record else "session_started"
        else:
            self.session_record = self.session_manager.create()
            session_event_type = "session_started"
        self.mode = self.session_record.current_mode
        self._emit_session_event(command.request_id, session_event_type=session_event_type)

    def list_sessions(self, command: FactoryFrontendCommand) -> None:
        self.emit(
            event(
                "sessions_listed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={"sessions": [_session_payload(item) for item in self.session_manager.list_sessions()]},
            )
        )

    def switch_session(self, command: FactoryFrontendCommand) -> None:
        if not command.session_id:
            self._emit_error(command, "switch_session requires session_id")
            return
        self.session_record = self.session_manager.load(command.session_id)
        self.mode = self.session_record.current_mode
        self.pending_agent_package_run = None
        self._emit_session_event(command.request_id, session_event_type="session_switched")

    def new_session(self, command: FactoryFrontendCommand) -> None:
        self.session_record = self.session_manager.create()
        self.mode = None
        self.pending_agent_package_run = None
        self._emit_session_event(command.request_id, session_event_type="session_started")

    def set_mode(self, command: FactoryFrontendCommand) -> None:
        self._ensure_session(command)
        if command.mode == "agent_package":
            self._emit_error(command, "use list_agent_packages/select_agent_package to enter agent package mode")
            return
        self.mode = command.mode
        self.session_record = self.session_manager.set_mode(self.session_record.session_id, self.mode)
        self.emit(
            event(
                "mode_changed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={
                    "mode": self.mode,
                    **({"package_id": SYSTEM_CHAT_PACKAGE_ID} if self.mode == "chat" else {}),
                    **({"package_id": SYSTEM_CREATE_AGENT_PACKAGE_ID} if self.mode == "create_agent" else {}),
                },
            )
        )

    def set_options(self, command: FactoryFrontendCommand) -> None:
        stop_after_stage = command.options.get("stop_after_stage", self.options.stop_after_stage)
        if stop_after_stage in {"", "off", "none"}:
            stop_after_stage = None
        if stop_after_stage is not None and stop_after_stage not in STAGE_IDS:
            self._emit_error(command, f"unknown stage_id: {stop_after_stage}")
            return
        self.options = FactoryBridgeOptions(
            stop_after_stage=stop_after_stage,
            show_state=bool(command.options.get("show_state", self.options.show_state)),
            show_messages=bool(command.options.get("show_messages", self.options.show_messages)),
        )
        self.emit(
            event(
                "runtime_options_changed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={"options": asdict(self.options)},
            )
        )

    def send_message(self, command: FactoryFrontendCommand) -> None:
        self._ensure_session(command)
        if self.mode not in {"chat", "create_agent"}:
            self._emit_error(command, "enter /chat or /create-agent before sending messages")
            return
        message = (command.message or "").strip()
        if not message:
            self._emit_error(command, "send_message requires message")
            return
        if self.pending_agent_package_run is not None:
            self._emit_error(command, "cannot send a new message while an interrupt is pending")
            return
        if self.mode == "chat":
            self._run_chat(command, message)
        else:
            self._run_create_agent(command, message)

    def resume_interrupt(self, command: FactoryFrontendCommand) -> None:
        if self.pending_agent_package_run is None:
            self._emit_error(command, "no pending interrupt to resume")
            return
        self._resume_agent_package_interrupt(command)

    def rerun_from_stage(self, command: FactoryFrontendCommand) -> None:
        self._ensure_session(command)
        stage_id = str(command.payload.get("stage_id") or "").strip()
        if self.mode != "create_agent":
            self._emit_error(command, "rerun_from_stage is only available in create_agent mode")
            return
        if self.pending_agent_package_run is not None:
            self._emit_error(command, "cannot rerun while an interrupt is pending")
            return
        if stage_id not in STAGE_IDS:
            self._emit_error(command, f"unknown stage_id: {stage_id}")
            return
        self._emit_error(
            command,
            f"RuntimeKernel bookmark rerun is not available for stage yet: {stage_id}",
        )

    def scheduler_manage(self, command: FactoryFrontendCommand) -> None:
        runtime = self.scheduler_runtime
        if runtime is None:
            self._emit_error(command, "scheduler runtime is not enabled")
            return
        action = str(command.payload.get("action") or "list").strip()
        job_id = str(command.payload.get("job_id") or "").strip()
        limit = _bounded_int(command.payload.get("limit"), default=20, minimum=1, maximum=200)
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
            self._emit_scheduler_event(
                SchedulerEventPayload(
                    event_type="scheduler_job_described",
                    job_id=job_id,
                    owner_type=runtime.owner_type,
                    owner_id=runtime.owner_id,
                    target_type=job_payload.get("target", {}).get("target_type") if isinstance(job_payload.get("target"), dict) else None,
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

    def list_agent_packages(self, command: FactoryFrontendCommand) -> None:
        packages = self.agent_package_runtime.list_packages()
        self.emit(
            event(
                "agent_packages_listed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode="agent_package",
                payload={"packages": packages},
            )
        )

    def select_agent_package(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        if not package_id:
            self._emit_error(command, "select_agent_package requires package_id")
            return
        package_info = self.agent_package_runtime.package_summary(package_id)
        sessions = self.agent_package_runtime.list_sessions(package_id)
        self.mode = "agent_package"
        self.emit(
            event(
                "agent_package_selected",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode="agent_package",
                payload={"package": package_info, "sessions": sessions},
            )
        )

    def delete_agent_package(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        if not package_id:
            self._emit_error(command, "delete_agent_package requires package_id")
            return
        result = self.agent_package_runtime.delete_package(package_id)
        packages = self.agent_package_runtime.list_packages()
        self.emit(
            event(
                "agent_package_deleted",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode="agent_package",
                payload={**result, "packages": packages},
            )
        )

    def list_agent_package_sessions(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        if not package_id:
            self._emit_error(command, "list_agent_package_sessions requires package_id")
            return
        sessions = self.agent_package_runtime.list_sessions(package_id)
        self.emit(
            event(
                "agent_package_sessions_listed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode="agent_package",
                payload={"package_id": package_id, "sessions": sessions},
            )
        )

    def run_agent_package(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        message = str(command.payload.get("message") or command.message or "").strip()
        session_id = str(command.payload.get("session_id") or "").strip() or None
        if not package_id:
            self._emit_error(command, "run_agent_package requires package_id")
            return
        if not message:
            self._emit_error(command, "run_agent_package requires message")
            return
        if self.pending_agent_package_run is not None:
            self._emit_error(command, "cannot run an agent package while an interrupt is pending")
            return
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=self._session_id(),
            mode="agent_package",
            graph_id="agent_package_runtime",
        )
        try:
            run = self.agent_package_runtime.stream(
                package_id,
                user_input=message,
                session_id=session_id,
                request_id=command.request_id,
            )
            self._consume_agent_package_stream(
                package_id=package_id,
                run=run,
                normalizer=normalizer,
            )
        except Exception as exc:
            normalizer.emit_run_failed(exc)

    def _resume_agent_package_interrupt(self, command: FactoryFrontendCommand) -> None:
        pending = self.pending_agent_package_run
        self.pending_agent_package_run = None
        if pending is None:
            self._emit_error(command, "no pending agent package interrupt to resume")
            return
        try:
            run = self.agent_package_runtime.resume_stream(
                pending.package_id,
                session_id=pending.session_id,
                resume_payload=command.payload,
                request_id=command.request_id,
            )
            self._consume_agent_package_stream(
                package_id=pending.package_id,
                run=run,
                normalizer=pending.normalizer,
                frontend_mode=pending.normalizer.mode if pending.normalizer.mode == "chat" else None,
                frontend_session_id=pending.normalizer.session_id if pending.normalizer.mode == "chat" else None,
            )
        except Exception as exc:
            pending.normalizer.emit_run_failed(exc)

    def cancel_runtime_request(self, command: FactoryFrontendCommand) -> None:
        reason = str(command.payload.get("reason") or "user_cancelled")
        if self.agent_package_runtime is not None:
            cancelled = self.agent_package_runtime.cancel_active_requests(reason=reason)
        else:
            cancelled = 0
        self.pending_agent_package_run = None
        self.emit(
            event(
                "debug_patch",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                graph_id="factory_runtime",
                producer_type="factory_runtime",
                payload={
                    "source": "runtime_request_cancel",
                    "reason": reason,
                    "cancelled_requests": cancelled,
                },
            )
        )

    def _consume_agent_package_stream(
        self,
        *,
        package_id: str,
        run: Any,
        normalizer: RuntimeEventNormalizer,
        frontend_mode: FactoryMode | None = None,
        frontend_session_id: str | None = None,
    ) -> None:
        final_state = None
        terminal_event_seen = False
        for stream_mode, chunk in run.events:
            if stream_mode == "frontend_event":
                item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
                agent_session_id = item.session_id
                if agent_session_id:
                    run.session["session_id"] = agent_session_id
                if item.event_type in {"run_completed", "run_failed"}:
                    terminal_event_seen = True
                if item.event_type == "run_completed" and frontend_mode == "chat":
                    self._sync_system_chat_session_summary(item)
                if item.event_type == "run_completed" and frontend_mode == "create_agent":
                    self._sync_system_create_agent_session_summary(item)
                if item.event_type in {"tool_approval_requested", "interrupt_requested"}:
                    session_id = str(agent_session_id or (run.session or {}).get("session_id") or "")
                    if not session_id:
                        raise RuntimeError("agent package interrupt missing session_id")
                    self.pending_agent_package_run = PendingAgentPackageRun(
                        package_id=package_id,
                        session_id=session_id,
                        normalizer=normalizer,
                    )
                self.emit(_frontend_scoped_agent_event(item, mode=frontend_mode, session_id=frontend_session_id))
                if item.event_type in {"tool_approval_requested", "interrupt_requested"}:
                    return
                continue
            if stream_mode == "stderr":
                normalizer.runtime_event(
                    "debug_patch",
                    span_id=normalizer.run_span_id,
                    payload={"agent_package_stderr": json_safe(chunk)},
                )
                continue
            interrupt_payload = _extract_interrupt_payload(chunk)
            if interrupt_payload is not None:
                session_id = str((run.session or {}).get("session_id") or "")
                if not session_id:
                    raise RuntimeError("agent package interrupt missing session_id")
                self.pending_agent_package_run = PendingAgentPackageRun(
                    package_id=package_id,
                    session_id=session_id,
                    normalizer=normalizer,
                )
                normalizer.emit_interrupt(json_safe(interrupt_payload))
                return
            if stream_mode == "messages":
                normalizer.emit_message_chunk(chunk)
            elif stream_mode == "debug":
                normalizer.emit_debug_event(json_safe(chunk))
            elif stream_mode == "custom":
                normalizer.emit_custom_event(json_safe(chunk))
            elif stream_mode == "updates":
                normalizer.runtime_event(
                    "debug_patch",
                    span_id=normalizer.run_span_id,
                    payload={"agent_package_update": json_safe(chunk)},
                )
            elif stream_mode == "runtime_final":
                final_state = chunk
        if terminal_event_seen:
            return
        if final_state is None:
            raise RuntimeError("agent package runtime did not produce a final state")
        if not runtime_completed(final_state):
            normalizer.complete_open_model_streams(reason="run_failed")
            normalizer.emit_run_failed(RuntimeError(runtime_error_message(final_state, command="agent package runtime")))
            return
        normalizer.complete_open_model_streams(reason="run_completed")
        normalizer.emit_run_completed(
            {
                "status": final_state.execution.finish_status,
                "package_id": package_id,
                "agent_id": run.package.assembly_spec.agent.id,
                "agent_session": run.session,
            }
        )

    def _run_chat(self, command: FactoryFrontendCommand, message: str) -> None:
        agent_session_id = self._ensure_system_chat_agent_session(message)
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=self._session_id(),
            mode="chat",
            graph_id="factory_chat_package",
            producer_type="factory_runtime",
        )
        try:
            run = self.agent_package_runtime.stream(
                SYSTEM_CHAT_PACKAGE_ID,
                user_input=message,
                session_id=agent_session_id,
                request_id=command.request_id,
            )
            self._consume_agent_package_stream(
                package_id=SYSTEM_CHAT_PACKAGE_ID,
                run=run,
                normalizer=normalizer,
                frontend_mode="chat",
                frontend_session_id=self._session_id(),
            )
        except Exception as exc:
            normalizer.emit_run_failed(exc)

    def _run_create_agent(self, command: FactoryFrontendCommand, message: str) -> None:
        agent_session_id = self._ensure_system_create_agent_session(message)
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=self._session_id(),
            mode="create_agent",
            graph_id="factory_create_agent_package",
            producer_type="factory_runtime",
        )
        try:
            run = self.agent_package_runtime.stream(
                SYSTEM_CREATE_AGENT_PACKAGE_ID,
                user_input=message,
                session_id=agent_session_id,
                request_id=command.request_id,
                user_config={"stop_after_stage": self.options.stop_after_stage},
            )
            self._consume_agent_package_stream(
                package_id=SYSTEM_CREATE_AGENT_PACKAGE_ID,
                run=run,
                normalizer=normalizer,
                frontend_mode="create_agent",
                frontend_session_id=self._session_id(),
            )
        except Exception as exc:
            normalizer.emit_run_failed(exc)

    def _sync_system_chat_session_summary(self, item: FactoryFrontendEvent) -> None:
        if self.session_record is None:
            return
        agent_session = item.payload.get("agent_session") if isinstance(item.payload, dict) else None
        if isinstance(agent_session, dict):
            self.session_record.chat_agent_package_session_id = str(
                agent_session.get("session_id") or self.session_record.chat_agent_package_session_id or ""
            ) or None
            try:
                self.session_record.chat_turn_count = int(agent_session.get("turn_count") or self.session_record.chat_turn_count)
            except (TypeError, ValueError):
                pass
        self.session_manager.save(self.session_record)

    def _sync_system_create_agent_session_summary(self, item: FactoryFrontendEvent) -> None:
        if self.session_record is None:
            return
        agent_session = item.payload.get("agent_session") if isinstance(item.payload, dict) else None
        if isinstance(agent_session, dict):
            self.session_record.create_agent_package_session_id = str(
                agent_session.get("session_id") or self.session_record.create_agent_package_session_id or ""
            ) or None
            try:
                self.session_record.create_agent_turn_count = int(
                    agent_session.get("turn_count") or self.session_record.create_agent_turn_count
                )
            except (TypeError, ValueError):
                pass
        self.session_manager.save(self.session_record)

    def _emit_session_event(self, request_id: str | None, *, session_event_type: str = "session_switched") -> None:
        self.emit(
            event(
                session_event_type,
                request_id=request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={"session": _session_payload(self.session_record)},
            )
        )

    def _emit_error(self, command: FactoryFrontendCommand, message: str) -> None:
        self.emit(
            event(
                "error",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                message=message,
            )
        )

    def _ensure_session(self, command: FactoryFrontendCommand) -> None:
        if self.session_record is None:
            self.start_session(FactoryFrontendCommand(type="start_session", request_id=command.request_id))

    def _ensure_system_chat_agent_session(self, first_user_input: str) -> str:
        if self.session_record is None:
            self.start_session(FactoryFrontendCommand(type="start_session"))
        self.session_record = self.session_manager.remember_first_user_input(
            self.session_record.session_id,
            first_user_input,
        )
        agent_session = self.agent_package_runtime.ensure_session(
            SYSTEM_CHAT_PACKAGE_ID,
            session_id=self.session_record.chat_agent_package_session_id,
            first_user_input=first_user_input,
        )
        agent_session_id = str(agent_session.get("session_id") or "")
        if agent_session_id != self.session_record.chat_agent_package_session_id:
            self.session_record.chat_agent_package_session_id = agent_session_id
            self.session_manager.save(self.session_record)
        return agent_session_id

    def _ensure_system_create_agent_session(self, first_user_input: str) -> str:
        if self.session_record is None:
            self.start_session(FactoryFrontendCommand(type="start_session"))
        self.session_record = self.session_manager.remember_first_user_input(
            self.session_record.session_id,
            first_user_input,
        )
        agent_session = self.agent_package_runtime.ensure_session(
            SYSTEM_CREATE_AGENT_PACKAGE_ID,
            session_id=self.session_record.create_agent_package_session_id,
            first_user_input=first_user_input,
        )
        agent_session_id = str(agent_session.get("session_id") or "")
        if agent_session_id != self.session_record.create_agent_package_session_id:
            self.session_record.create_agent_package_session_id = agent_session_id
            self.session_manager.save(self.session_record)
        return agent_session_id

    def _session_id(self) -> str | None:
        if self.session_record is None:
            return None
        return str(self.session_record.session_id)

    def checkpointer_payload(self) -> dict[str, Any]:
        return {
            "backend": "system_package",
            "persistent": True,
            "path": None,
        }

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
        self.emit(
            event(
                payload.event_type,
                session_id=self._session_id(),
                mode=self.mode,
                graph_id="factory_scheduler",
                producer_type="factory_runtime",
                severity="error" if payload.event_type.endswith("failed") else None,
                payload={key: value for key, value in payload.model_dump(mode="json").items() if key != "event_type"},
            )
        )

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
        package_id = SYSTEM_CHAT_PACKAGE_ID if mode == "chat" else SYSTEM_CREATE_AGENT_PACKAGE_ID
        agent_session_id = (
            self._ensure_system_chat_agent_session(message)
            if mode == "chat"
            else self._ensure_system_create_agent_session(message)
        )
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=None,
            session_id=self._session_id(),
            mode=mode,  # type: ignore[arg-type]
            graph_id=f"factory_{mode}_package_scheduler",
            producer_type="factory_runtime",
        )
        try:
            run = self.agent_package_runtime.stream(
                package_id,
                user_input=message,
                session_id=agent_session_id,
                request_id=None,
                user_config={"stop_after_stage": self.options.stop_after_stage} if mode == "create_agent" else None,
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

    def _factory_tools(self, tool_ids: list[str] | set[str] | tuple[str, ...] | None = None) -> list[Any]:
        return get_factory_tools(
            tool_ids=tool_ids,
            tool_runtime_resources=self._factory_tool_runtime_resources(),
        )

    def _factory_tool_runtime_resources(self) -> dict[str, Any]:
        if self.scheduler_runtime is None:
            return {}
        return {"scheduler_runtime": self.scheduler_runtime}


def _session_payload(record: Any | None) -> dict[str, Any]:
    if record is None:
        return {}
    payload = record.model_dump(mode="json")
    first_user_input = payload.get("first_user_input")
    payload["first_user_input"] = first_user_input
    payload["display_title"] = payload.get("display_title") or _display_title(first_user_input)
    mode = payload.get("current_mode")
    payload["snapshot"] = {
        "mode": mode,
        "messages": [],
        "pending_interrupt": None,
        "recent_tool_activities": [],
    }
    return payload


def _frontend_scoped_agent_event(
    item: FactoryFrontendEvent,
    *,
    mode: FactoryMode | None,
    session_id: str | None,
) -> FactoryFrontendEvent:
    updates: dict[str, Any] = {}
    if mode is not None:
        updates["mode"] = mode
    if session_id is not None:
        updates["session_id"] = session_id
    return item.model_copy(update=updates) if updates else item


def _display_title(value: str | None, *, limit: int = 42) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 1]}…"


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _extract_interrupt_payload(chunk: Any) -> Any | None:
    if not isinstance(chunk, dict):
        return None
    interrupts = chunk.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return getattr(first, "value", first)
