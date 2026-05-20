from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable
import uuid

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.factory_graph.chat_graph import build_factory_chat_graph, initial_factory_chat_state
from agent_factory.factory_graph.constants import DEFAULT_CREATE_AGENT_BREAKPOINT_STAGE, STAGE_IDS
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer, json_safe
from agent_factory.factory_graph.frontend_bridge.protocol import (
    FactoryFrontendCommand,
    FactoryFrontendEvent,
    FactoryMode,
    event,
)
from agent_factory.factory_graph.graph import build_factory_graph, initial_factory_graph_state
from agent_factory.factory_graph.session import (
    FactorySessionManager,
    build_factory_checkpointer_handle,
    is_factory_checkpointer_persistent,
)
from agent_factory.memory_system.factory import enqueue_factory_memory_write
from agent_factory.memory_system.config import memory_write_interval_turns_from_env
from agent_factory.memory_system.namespace import factory_memory_namespace
from agent_factory.memory_system.reports import memory_event_payload
from agent_factory.memory_system.segment import build_conversation_segment
from agent_factory.scheduler_system import (
    SchedulerExecutor,
    SchedulerWorker,
    deny_if_unattended_approval_required,
    default_factory_scheduler_runtime,
    scheduler_enabled_from_env,
)
from agent_factory.scheduler_system.events import SchedulerEventPayload
from agent_factory.tooling import get_factory_base_tool_ids
from agent_factory.tooling import get_factory_tools


Emit = Callable[[FactoryFrontendEvent], None]


@dataclass(slots=True)
class FactoryBridgeOptions:
    stop_after_stage: str | None = DEFAULT_CREATE_AGENT_BREAKPOINT_STAGE
    show_state: bool = False
    show_messages: bool = True


@dataclass(slots=True)
class PendingRun:
    mode: FactoryMode
    app: Any
    config: dict[str, Any]
    last_state: dict[str, Any]
    normalizer: RuntimeEventNormalizer


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
    pending_run: PendingRun | None = None
    pending_agent_package_run: PendingAgentPackageRun | None = None
    agent_package_runtime: AgentPackageRuntimeManager | None = None
    scheduler_worker: SchedulerWorker | None = None

    def __post_init__(self) -> None:
        load_agentfactory_dotenv()
        if self.session_manager is None:
            self.session_manager = FactorySessionManager.from_env()
        if self.checkpointer is None:
            self.checkpointer_handle = build_factory_checkpointer_handle()
            self.checkpointer = self.checkpointer_handle.saver
        if self.agent_package_runtime is None:
            self.agent_package_runtime = AgentPackageRuntimeManager()
        if scheduler_enabled_from_env():
            self._start_factory_scheduler()

    def handle(self, command: FactoryFrontendCommand) -> bool:
        try:
            if command.type == "shutdown":
                if self.agent_package_runtime is not None:
                    self.agent_package_runtime.close_all()
                if self.scheduler_worker is not None:
                    self.scheduler_worker.shutdown()
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
        self.pending_run = None
        self._emit_session_event(command.request_id, session_event_type="session_switched")

    def new_session(self, command: FactoryFrontendCommand) -> None:
        self.session_record = self.session_manager.create()
        self.mode = None
        self.pending_run = None
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
                payload={"mode": self.mode},
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
        if self.pending_run is not None:
            self._emit_error(command, "cannot send a new message while an interrupt is pending")
            return
        if self.mode == "chat":
            self._run_chat(command, message)
        else:
            self._run_create_agent(command, message)

    def resume_interrupt(self, command: FactoryFrontendCommand) -> None:
        if self.pending_run is None and self.pending_agent_package_run is None:
            self._emit_error(command, "no pending interrupt to resume")
            return
        if self.pending_agent_package_run is not None:
            self._resume_agent_package_interrupt(command)
            return
        pending = self.pending_run
        self.pending_run = None
        pending.normalizer.emit_runtime_resumed(command.payload)
        self._stream_run(
            request_id=command.request_id,
            mode=pending.mode,
            app=pending.app,
            stream_input=Command(resume=command.payload),
            config=pending.config,
            initial_final_state=pending.last_state,
            normalizer=pending.normalizer,
            emit_run_started=False,
        )

    def rerun_from_stage(self, command: FactoryFrontendCommand) -> None:
        self._ensure_session(command)
        stage_id = str(command.payload.get("stage_id") or "").strip()
        if self.mode != "create_agent":
            self._emit_error(command, "rerun_from_stage is only available in create_agent mode")
            return
        if self.pending_run is not None:
            self._emit_error(command, "cannot rerun while an interrupt is pending")
            return
        if stage_id not in STAGE_IDS:
            self._emit_error(command, f"unknown stage_id: {stage_id}")
            return
        app = build_factory_graph(
            stop_after_stage=self.options.stop_after_stage,
            enable_interrupts=True,
            checkpointer=self.checkpointer,
        )
        base_config = {"configurable": {"thread_id": self._thread_id("create_agent")}}
        snapshot = _latest_stage_entry_snapshot(app, config=base_config, stage_id=stage_id)
        if snapshot is None:
            self._emit_error(command, f"no checkpoint found at stage entry: {stage_id}")
            return
        self.pending_run = None
        initial_state = dict(snapshot.values or {}) if isinstance(snapshot.values, dict) else {}
        checkpoint_config = dict(snapshot.config or base_config)
        self._stream_run(
            request_id=command.request_id,
            mode="create_agent",
            app=app,
            stream_input=None,
            config=checkpoint_config,
            initial_final_state=initial_state,
            run_started_payload={
                "stop_after_stage": self.options.stop_after_stage,
                "rerun_from_stage": stage_id,
                "checkpoint": _checkpoint_payload(checkpoint_config),
            },
        )

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
        if self.pending_run is not None or self.pending_agent_package_run is not None:
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
            )
        except Exception as exc:
            pending.normalizer.emit_run_failed(exc)

    def _consume_agent_package_stream(
        self,
        *,
        package_id: str,
        run: Any,
        normalizer: RuntimeEventNormalizer,
    ) -> None:
        final_state = None
        terminal_event_seen = False
        for stream_mode, chunk in run.events:
            if stream_mode == "frontend_event":
                item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
                if item.session_id:
                    run.session["session_id"] = item.session_id
                if item.event_type in {"run_completed", "run_failed"}:
                    terminal_event_seen = True
                if item.event_type == "interrupt_requested":
                    session_id = str(item.session_id or (run.session or {}).get("session_id") or "")
                    if not session_id:
                        raise RuntimeError("agent package interrupt missing session_id")
                    self.pending_agent_package_run = PendingAgentPackageRun(
                        package_id=package_id,
                        session_id=session_id,
                        normalizer=normalizer,
                    )
                self.emit(item)
                if item.event_type == "interrupt_requested":
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
        self.session_record = self.session_manager.remember_first_user_input(self.session_record.session_id, message)
        new_message = HumanMessage(content=message)
        messages: list[BaseMessage] = [new_message]
        if not self._use_checkpoint_memory():
            messages = [*self.session_manager.messages(self.session_record, "chat"), new_message]
        app = build_factory_chat_graph(enable_interrupts=True, checkpointer=self.checkpointer)
        initial_state = initial_factory_chat_state(messages)
        self._stream_run(
            request_id=command.request_id,
            mode="chat",
            app=app,
            stream_input=initial_state,
            config={"configurable": {"thread_id": self._thread_id("chat")}},
            initial_final_state=initial_state,
        )

    def _run_create_agent(self, command: FactoryFrontendCommand, message: str) -> None:
        self.session_record = self.session_manager.remember_first_user_input(self.session_record.session_id, message)
        new_message = HumanMessage(content=message)
        messages: list[BaseMessage] = [new_message]
        if not self._use_checkpoint_memory():
            messages = [*self.session_manager.messages(self.session_record, "create_agent"), new_message]
        app = build_factory_graph(
            stop_after_stage=self.options.stop_after_stage,
            enable_interrupts=True,
            checkpointer=self.checkpointer,
        )
        initial_state = initial_factory_graph_state(
            requirement=message,
            messages=messages,
            force_manufacture=True,
            interaction_mode="create_agent",
        )
        self._stream_run(
            request_id=command.request_id,
            mode="create_agent",
            app=app,
            stream_input=initial_state,
            config={"configurable": {"thread_id": self._thread_id("create_agent")}},
            initial_final_state=initial_state,
        )

    def _stream_run(
        self,
        *,
        request_id: str | None,
        mode: FactoryMode,
        app: Any,
        stream_input: Any,
        config: dict[str, Any],
        initial_final_state: dict[str, Any],
        normalizer: RuntimeEventNormalizer | None = None,
        emit_run_started: bool = True,
        run_started_payload: dict[str, Any] | None = None,
    ) -> None:
        normalizer = normalizer or RuntimeEventNormalizer(
            emit=self.emit,
            request_id=request_id,
            session_id=self._session_id(),
            mode=mode,
            graph_id="factory_chat_graph" if mode == "chat" else "factory_graph",
        )
        if emit_run_started:
            normalizer.emit_run_started(run_started_payload or {"stop_after_stage": self.options.stop_after_stage})
        final_state = initial_final_state
        try:
            for stream_mode, chunk in app.stream(
                stream_input,
                config=config,
                stream_mode=["updates", "values", "messages", "debug", "custom"],
            ):
                interrupt_payload = _extract_interrupt_payload(chunk)
                if interrupt_payload is not None:
                    self.pending_run = PendingRun(
                        mode=mode,
                        app=app,
                        config=config,
                        last_state=final_state,
                        normalizer=normalizer,
                    )
                    normalizer.emit_interrupt(json_safe(interrupt_payload))
                    return
                if stream_mode == "updates":
                    self._emit_updates(normalizer, chunk)
                elif stream_mode == "values":
                    final_state = chunk
                elif stream_mode == "messages":
                    normalizer.emit_message_chunk(chunk)
                elif stream_mode == "debug":
                    normalizer.emit_debug_event(json_safe(chunk))
                elif stream_mode == "custom":
                    normalizer.emit_custom_event(json_safe(chunk))
            can_commit_messages = _can_commit_session_messages(final_state)
            if can_commit_messages:
                self._save_messages(mode, final_state)
                self._enqueue_factory_memory(normalizer, mode, config, final_state)
            normalizer.emit_run_completed(_summary_payload(final_state, self.options))
        except Exception as exc:
            normalizer.emit_run_failed(exc)

    def _emit_updates(self, normalizer: RuntimeEventNormalizer, chunk: Any) -> None:
        if not isinstance(chunk, dict):
            return
        for node_id, patch in chunk.items():
            normalizer.emit_update(str(node_id), json_safe(patch))

    def _save_messages(self, mode: FactoryMode, final_state: dict[str, Any]) -> None:
        if self.session_record is None:
            return
        messages = final_state.get("messages", [])
        self.session_record = self.session_manager.replace_messages(
            self.session_record.session_id,
            mode,
            messages,
        )

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

    def _enqueue_factory_memory(
        self,
        normalizer: RuntimeEventNormalizer,
        mode: FactoryMode,
        config: dict[str, Any],
        final_state: dict[str, Any],
    ) -> None:
        if final_state.get("status") in {"failed", "blocked"} or final_state.get("errors"):
            return
        configurable = dict(config.get("configurable") or {})
        turn_index = _factory_turn_count(self.session_record, mode, fallback_messages=final_state.get("messages", []))
        source = {
            "session_id": self._session_id(),
            "thread_id": configurable.get("thread_id"),
            "mode": mode,
            "run_id": final_state.get("factory_run_id") or final_state.get("run_id"),
            "node_id": final_state.get("current_stage"),
        }
        segment = build_conversation_segment(
            scope="factory",
            namespace=factory_memory_namespace("default"),
            source=source,
            messages=final_state.get("messages", []),
            end_turn=turn_index,
            max_turns=memory_write_interval_turns_from_env(),
        )
        if segment is None:
            return
        try:
            report = enqueue_factory_memory_write(segment=segment)
            if report.status == "noop":
                return
            event_type = "memory_write_queued" if report.status == "queued" else "memory_write_queued_failed"
            normalizer.emit_custom_event(
                {
                    "type": "memory_event",
                    "payload": {"event_type": event_type, **memory_event_payload(report)},
                }
            )
        except Exception as exc:
            normalizer.emit_custom_event(
                {
                    "type": "memory_event",
                    "payload": {
                        "event_type": "memory_write_queued_failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                }
            )

    def _ensure_session(self, command: FactoryFrontendCommand) -> None:
        if self.session_record is None:
            self.start_session(FactoryFrontendCommand(type="start_session", request_id=command.request_id))

    def _session_id(self) -> str | None:
        if self.session_record is None:
            return None
        return str(self.session_record.session_id)

    def _thread_id(self, mode: FactoryMode) -> str:
        if self.session_record is None:
            return f"factory-{mode}-{uuid.uuid4().hex}"
        return self.session_manager.thread_id(self.session_record, mode)

    def _use_checkpoint_memory(self) -> bool:
        return is_factory_checkpointer_persistent(self.checkpointer)

    def checkpointer_payload(self) -> dict[str, Any]:
        if self.checkpointer_handle is not None:
            return {
                "backend": self.checkpointer_handle.backend,
                "persistent": self.checkpointer_handle.persistent,
                "path": str(self.checkpointer_handle.path) if self.checkpointer_handle.path else None,
            }
        return {
            "backend": "external",
            "persistent": self._use_checkpoint_memory(),
            "path": None,
        }

    def _start_factory_scheduler(self) -> None:
        runtime = default_factory_scheduler_runtime(event_sink=self._emit_scheduler_event)
        runtime.executor = SchedulerExecutor(
            graph_runner=self._scheduler_graph_runner,
            tool_runner=self._scheduler_tool_runner,
        )
        worker = SchedulerWorker(runtime)
        try:
            worker.start()
            self.scheduler_worker = worker
        except Exception as exc:
            self._emit_scheduler_event(
                SchedulerEventPayload(
                    event_type="scheduler_run_failed",
                    owner_type="factory",
                    owner_id="default",
                    status="failed",
                    error_summary=f"{type(exc).__name__}: {exc}",
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
        tools = {tool.name: tool for tool in get_factory_tools()}
        tool = tools.get(tool_id)
        if tool is None:
            return {"status": "failed", "error": f"unknown factory tool: {tool_id}"}
        denial = deny_if_unattended_approval_required(job=job, tool_id=tool_id, model_tool=tool)
        if denial is not None:
            return denial
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
        new_message = HumanMessage(content=message)
        if mode == "chat":
            app = build_factory_chat_graph(enable_interrupts=True, checkpointer=self.checkpointer)
            initial_state = initial_factory_chat_state([new_message])
            graph_id = "factory_chat_scheduler"
        else:
            app = build_factory_graph(
                stop_after_stage=self.options.stop_after_stage,
                enable_interrupts=True,
                checkpointer=self.checkpointer,
            )
            initial_state = initial_factory_graph_state(
                requirement=message,
                messages=[new_message],
                force_manufacture=True,
                interaction_mode="create_agent",
            )
            graph_id = "factory_create_agent_scheduler"
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=None,
            session_id=self._session_id(),
            mode=mode,  # type: ignore[arg-type]
            graph_id=graph_id,
        )
        self._stream_run(
            request_id=None,
            mode=mode,  # type: ignore[arg-type]
            app=app,
            stream_input=initial_state,
            config={"configurable": {"thread_id": f"factory-scheduler-{job.job_id}"}},
            initial_final_state=initial_state,
            normalizer=normalizer,
            run_started_payload={"scheduler_job_id": job.job_id, "trigger": "scheduler"},
        )
        return {"status": "completed", "output_summary": f"factory scheduled {mode} run completed"}


def _session_payload(record: Any | None) -> dict[str, Any]:
    if record is None:
        return {}
    payload = record.model_dump(mode="json")
    first_user_input = payload.get("first_user_input") or _first_message_content(payload.get("create_agent_messages"))
    first_user_input = first_user_input or _first_message_content(payload.get("chat_messages"))
    payload["first_user_input"] = first_user_input
    payload["display_title"] = payload.get("display_title") or _display_title(first_user_input)
    mode = payload.get("current_mode")
    active_messages = payload.get("chat_messages") if mode == "chat" else payload.get("create_agent_messages") if mode == "create_agent" else []
    payload["snapshot"] = {
        "mode": mode,
        "messages": json_safe(active_messages or []),
        "pending_interrupt": None,
        "recent_tool_activities": [],
    }
    return payload


def _first_message_content(messages: Any) -> str | None:
    if not isinstance(messages, list):
        return None
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("role") == "user" and isinstance(message.get("content"), str):
            value = message["content"].strip()
            if value:
                return value
    return None


def _display_title(value: str | None, *, limit: int = 42) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 1]}…"


def _summary_payload(final_state: dict[str, Any], options: FactoryBridgeOptions) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": final_state.get("status"),
        "current_stage": final_state.get("current_stage"),
        "stage_log_count": len(final_state.get("stage_log", [])),
        "message_count": len(final_state.get("messages", [])),
        "error_count": len(final_state.get("errors", [])),
    }
    if options.show_state:
        payload["state"] = json_safe(final_state)
    if options.show_messages:
        payload["messages"] = json_safe(final_state.get("messages", []))
    return payload


def _can_commit_session_messages(final_state: dict[str, Any]) -> bool:
    if final_state.get("status") in {"failed", "blocked"}:
        return False
    if final_state.get("errors"):
        return False
    messages = final_state.get("messages", [])
    if not isinstance(messages, list):
        return False
    return _has_complete_tool_call_history(messages)


def _factory_turn_count(record: Any | None, mode: FactoryMode, *, fallback_messages: Any) -> int:
    if record is not None:
        if mode == "chat":
            count = int(getattr(record, "chat_turn_count", 0) or 0)
        else:
            count = int(getattr(record, "create_agent_turn_count", 0) or 0)
        if count > 0:
            return count
    if isinstance(fallback_messages, list):
        return sum(1 for message in fallback_messages if isinstance(message, HumanMessage))
    return 0


def _has_complete_tool_call_history(messages: list[Any]) -> bool:
    pending_tool_call_ids: set[str] = set()
    for message in messages:
        tool_calls = getattr(message, "tool_calls", None) or []
        if isinstance(message, AIMessage) and tool_calls:
            if pending_tool_call_ids:
                return False
            pending_tool_call_ids = {
                str(tool_call.get("id") or "")
                for tool_call in tool_calls
                if tool_call.get("id")
            }
            if not pending_tool_call_ids:
                return False
            continue
        if isinstance(message, ToolMessage):
            tool_call_id = str(getattr(message, "tool_call_id", "") or "")
            if tool_call_id in pending_tool_call_ids:
                pending_tool_call_ids.remove(tool_call_id)
            continue
        if pending_tool_call_ids:
            return False
    return not pending_tool_call_ids


def _latest_stage_entry_snapshot(app: Any, *, config: dict[str, Any], stage_id: str) -> Any | None:
    for snapshot in app.get_state_history(config):
        if stage_id in tuple(getattr(snapshot, "next", ()) or ()):
            return snapshot
    return None


def _checkpoint_payload(config: dict[str, Any]) -> dict[str, Any]:
    configurable = dict(config.get("configurable") or {})
    return {
        "thread_id": configurable.get("thread_id"),
        "checkpoint_id": configurable.get("checkpoint_id"),
        "checkpoint_ns": configurable.get("checkpoint_ns"),
    }


def _extract_interrupt_payload(chunk: Any) -> Any | None:
    if not isinstance(chunk, dict):
        return None
    interrupts = chunk.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return getattr(first, "value", first)
