from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable
import uuid

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.factory_graph.chat_graph import (
    FACTORY_CHAT_TOOLS_NODE,
    build_factory_chat_graph,
    initial_factory_chat_state,
)
from agent_factory.factory_graph.constants import DEFAULT_CREATE_AGENT_BREAKPOINT_STAGE, STAGE_IDS
from agent_factory.factory_graph.frontend_bridge.protocol import (
    FactoryFrontendCommand,
    FactoryFrontendEvent,
    FactoryMode,
    event,
)
from agent_factory.factory_graph.graph import (
    FACTORY_TOOLS_NODE,
    build_factory_graph,
    initial_factory_graph_state,
)
from agent_factory.factory_graph.session import (
    FactorySessionManager,
    build_factory_checkpointer,
    is_factory_checkpointer_persistent,
)
from agent_factory.factory_graph.tool_approval import FACTORY_TOOL_APPROVAL_NODE
from agent_factory.factory_graph.tools import get_factory_base_tool_ids


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


@dataclass(slots=True)
class FactoryRuntimeAdapter:
    emit: Emit
    session_manager: FactorySessionManager | None = None
    checkpointer: Any = None
    options: FactoryBridgeOptions = field(default_factory=FactoryBridgeOptions)
    session_record: Any | None = None
    mode: FactoryMode | None = None
    pending_run: PendingRun | None = None

    def __post_init__(self) -> None:
        load_agentfactory_dotenv()
        if self.session_manager is None:
            self.session_manager = FactorySessionManager.from_env()
        if self.checkpointer is None:
            self.checkpointer = build_factory_checkpointer()

    def handle(self, command: FactoryFrontendCommand) -> bool:
        try:
            if command.type == "shutdown":
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
        elif command.resume_latest:
            self.session_record = self.session_manager.latest() or self.session_manager.create()
        else:
            self.session_record = self.session_manager.create()
        self.mode = self.session_record.current_mode
        self._emit_session_changed(command.request_id)

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
        self._emit_session_changed(command.request_id)

    def new_session(self, command: FactoryFrontendCommand) -> None:
        self.session_record = self.session_manager.create()
        self.mode = None
        self.pending_run = None
        self._emit_session_changed(command.request_id)

    def set_mode(self, command: FactoryFrontendCommand) -> None:
        self._ensure_session(command)
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
                "stage_delta",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                node_id="bridge_options",
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
        if self.pending_run is None:
            self._emit_error(command, "no pending interrupt to resume")
            return
        pending = self.pending_run
        self.pending_run = None
        self._stream_run(
            request_id=command.request_id,
            mode=pending.mode,
            app=pending.app,
            stream_input=Command(resume=command.payload),
            config=pending.config,
            initial_final_state=pending.last_state,
        )

    def _run_chat(self, command: FactoryFrontendCommand, message: str) -> None:
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
        stream_input: dict[str, Any] | Command,
        config: dict[str, Any],
        initial_final_state: dict[str, Any],
    ) -> None:
        self.emit(
            event(
                "run_started",
                request_id=request_id,
                session_id=self._session_id(),
                mode=mode,
                payload={"stop_after_stage": self.options.stop_after_stage},
            )
        )
        final_state = initial_final_state
        try:
            for stream_mode, chunk in app.stream(
                stream_input,
                config=config,
                stream_mode=["updates", "values", "messages"],
            ):
                interrupt_payload = _extract_interrupt_payload(chunk)
                if interrupt_payload is not None:
                    self.pending_run = PendingRun(mode=mode, app=app, config=config, last_state=final_state)
                    self._emit_interrupt(request_id, mode, interrupt_payload)
                    return
                if stream_mode == "updates":
                    self._emit_updates(request_id, mode, chunk)
                elif stream_mode == "values":
                    final_state = chunk
                elif stream_mode == "messages":
                    self._emit_message_chunk(request_id, mode, chunk)
            self._save_messages(mode, final_state)
            self.emit(
                event(
                    "run_completed",
                    request_id=request_id,
                    session_id=self._session_id(),
                    mode=mode,
                    payload=_summary_payload(final_state, self.options),
                )
            )
        except Exception as exc:
            self.emit(
                event(
                    "run_failed",
                    request_id=request_id,
                    session_id=self._session_id(),
                    mode=mode,
                    message=f"{type(exc).__name__}: {exc}",
                )
            )

    def _emit_updates(self, request_id: str | None, mode: FactoryMode, chunk: Any) -> None:
        if not isinstance(chunk, dict):
            return
        for node_id, patch in chunk.items():
            safe_patch = _json_safe(patch)
            self.emit(
                event(
                    "stage_delta",
                    request_id=request_id,
                    session_id=self._session_id(),
                    mode=mode,
                    node_id=str(node_id),
                    stage_id=_stage_id_from_patch(safe_patch),
                    payload={"patch": safe_patch},
                )
            )
            self._emit_tool_results(request_id, mode, str(node_id), safe_patch)
            for item in safe_patch.get("stage_log", []) or []:
                self.emit(
                    event(
                        "stage_completed",
                        request_id=request_id,
                        session_id=self._session_id(),
                        mode=mode,
                        node_id=str(node_id),
                        stage_id=str(item.get("stage_id") or ""),
                        payload=item,
                    )
                )

    def _emit_message_chunk(self, request_id: str | None, mode: FactoryMode, chunk: Any) -> None:
        try:
            message_chunk, metadata = chunk
        except Exception:
            return
        if "nostream" in set(metadata.get("tags", [])):
            return
        if metadata.get("langgraph_node") in {FACTORY_TOOLS_NODE, FACTORY_CHAT_TOOLS_NODE}:
            return
        if isinstance(message_chunk, ToolMessage):
            return
        content = getattr(message_chunk, "content", "")
        if not content:
            return
        self.emit(
            event(
                "model_token",
                request_id=request_id,
                session_id=self._session_id(),
                mode=mode,
                node_id=str(metadata.get("langgraph_node") or ""),
                message=str(content),
            )
        )

    def _emit_tool_results(
        self,
        request_id: str | None,
        mode: FactoryMode,
        node_id: str,
        patch: dict[str, Any],
    ) -> None:
        for message in patch.get("messages", []) or []:
            if message.get("type") != "ToolMessage":
                continue
            self.emit(
                event(
                    "tool_result",
                    request_id=request_id,
                    session_id=self._session_id(),
                    mode=mode,
                    node_id=node_id,
                    payload=message,
                )
            )
        resource_plan = patch.get("resource_condition_plan") or {}
        for item in resource_plan.get("check_results", []) or []:
            self.emit(
                event(
                    "tool_result",
                    request_id=request_id,
                    session_id=self._session_id(),
                    mode=mode,
                    node_id=node_id,
                    payload={"resource_check": item},
                )
            )

    def _emit_interrupt(self, request_id: str | None, mode: FactoryMode, payload: Any) -> None:
        safe_payload = _json_safe(payload)
        interrupt_type = safe_payload.get("type") if isinstance(safe_payload, dict) else None
        if interrupt_type == "tool_approval":
            for request in safe_payload.get("requests", []) or []:
                self.emit(
                    event(
                        "tool_call_requested",
                        request_id=request_id,
                        session_id=self._session_id(),
                        mode=mode,
                        payload=request,
                    )
                )
        event_type = "resource_input_requested" if interrupt_type == "resource_input" else "interrupt_requested"
        self.emit(
            event(
                event_type,
                request_id=request_id,
                session_id=self._session_id(),
                mode=mode,
                payload=safe_payload if isinstance(safe_payload, dict) else {"value": safe_payload},
            )
        )

    def _save_messages(self, mode: FactoryMode, final_state: dict[str, Any]) -> None:
        if self.session_record is None:
            return
        messages = final_state.get("messages", [])
        self.session_record = self.session_manager.replace_messages(
            self.session_record.session_id,
            mode,
            messages,
        )

    def _emit_session_changed(self, request_id: str | None) -> None:
        self.emit(
            event(
                "session_changed",
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


def _session_payload(record: Any | None) -> dict[str, Any]:
    if record is None:
        return {}
    return record.model_dump(mode="json")


def _summary_payload(final_state: dict[str, Any], options: FactoryBridgeOptions) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": final_state.get("status"),
        "current_stage": final_state.get("current_stage"),
        "stage_log_count": len(final_state.get("stage_log", [])),
        "message_count": len(final_state.get("messages", [])),
        "error_count": len(final_state.get("errors", [])),
    }
    if options.show_state:
        payload["state"] = _json_safe(final_state)
    if options.show_messages:
        payload["messages"] = _json_safe(final_state.get("messages", []))
    return payload


def _stage_id_from_patch(patch: dict[str, Any]) -> str | None:
    if patch.get("current_stage"):
        return str(patch.get("current_stage"))
    stage_log = patch.get("stage_log") or []
    if stage_log:
        return str(stage_log[-1].get("stage_id") or "")
    return None


def _extract_interrupt_payload(chunk: Any) -> Any | None:
    if not isinstance(chunk, dict):
        return None
    interrupts = chunk.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return getattr(first, "value", first)


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseMessage):
        payload: dict[str, Any] = {
            "type": value.__class__.__name__,
            "content": getattr(value, "content", ""),
            "name": getattr(value, "name", None),
        }
        tool_calls = getattr(value, "tool_calls", None)
        if tool_calls:
            payload["tool_calls"] = tool_calls
        tool_call_id = getattr(value, "tool_call_id", None)
        if tool_call_id:
            payload["tool_call_id"] = tool_call_id
        return payload
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
