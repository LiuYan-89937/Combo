from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent_factory.create_agent.assist_workflow import CreateAgentAssistWorkflow
from agent_factory.create_agent.intent import classify_create_agent_intent
from agent_factory.create_agent.models import CreateAgentPublishDecision
from agent_factory.create_agent.tooling import CreateAgentToolEnvironmentBuilder
from agent_factory.create_agent.validation_state import package_fingerprint
from agent_factory.create_agent.workflow import CreateAgentWorkflow
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import extract_interrupt_payload
from agent_factory.factory_graph.session import build_factory_checkpointer_handle


@dataclass(frozen=True, slots=True)
class CreateAgentStreamRun:
    session_id: str
    workspace: CreateAgentWorkspace
    events: Iterator[tuple[str, Any]]


class CreateAgentRuntime:
    def __init__(
        self,
        *,
        tool_environment_builder: CreateAgentToolEnvironmentBuilder | None = None,
        checkpointer: Any | None = None,
        model: Any | None = None,
    ) -> None:
        self.tool_environment_builder = tool_environment_builder or CreateAgentToolEnvironmentBuilder()
        self.checkpointer = checkpointer or build_factory_checkpointer_handle().saver
        self.model = model
        self._active_graph_by_session: dict[str, str] = {}

    def stream(
        self,
        *,
        user_input: str,
        session_id: str | None,
        request_id: str | None,
    ) -> CreateAgentStreamRun:
        resolved_session_id = session_id or uuid4().hex
        workspace = CreateAgentWorkspace.for_session(resolved_session_id)
        intent = classify_create_agent_intent(
            user_input=user_input,
            workspace=workspace,
            model=self.model,
        )
        graph_kind = "manufacture" if intent.intent == "manufacture_agent" else "assist"
        self._active_graph_by_session[resolved_session_id] = graph_kind
        if graph_kind == "manufacture":
            workspace.initialize(user_input=user_input)
        else:
            workspace.root.mkdir(parents=True, exist_ok=True)
        return CreateAgentStreamRun(
            session_id=resolved_session_id,
            workspace=workspace,
            events=self._events(
                user_input=user_input,
                session_id=resolved_session_id,
                request_id=request_id,
                workspace=workspace,
                resume_payload=None,
                graph_kind=graph_kind,
                intent=intent.model_dump(mode="json"),
            ),
        )

    def resume_stream(
        self,
        *,
        session_id: str,
        resume_payload: dict[str, Any] | None,
        request_id: str | None,
    ) -> CreateAgentStreamRun:
        workspace = CreateAgentWorkspace.for_session(session_id)
        graph_kind = self._active_graph_by_session.get(session_id, "manufacture")
        return CreateAgentStreamRun(
            session_id=session_id,
            workspace=workspace,
            events=self._events(
                user_input="",
                session_id=session_id,
                request_id=request_id,
                workspace=workspace,
                resume_payload=resume_payload or {},
                graph_kind=graph_kind,
                intent=None,
            ),
        )

    def _events(
        self,
        *,
        user_input: str,
        session_id: str,
        request_id: str | None,
        workspace: CreateAgentWorkspace,
        resume_payload: dict[str, Any] | None,
        graph_kind: str,
        intent: dict[str, Any] | None,
    ) -> Iterator[tuple[str, Any]]:
        request_id = request_id or uuid4().hex
        graph_id = "create_agent_react" if graph_kind == "manufacture" else "create_agent_assist"
        node_label = "Create Agent ReAct" if graph_kind == "manufacture" else "Create Agent Assist"
        if resume_payload is None and graph_kind == "manufacture":
            workspace.reset_manufacturing_trace(
                session_id=session_id,
                request_id=request_id,
                graph_id=graph_id,
            )
        trace_sequence = workspace.manufacturing_trace_record_count() if graph_kind == "manufacture" else 0

        def record_trace(kind: str, payload: dict[str, Any]) -> None:
            nonlocal trace_sequence
            if graph_kind != "manufacture":
                return
            trace_sequence += 1
            workspace.append_manufacturing_trace_record(
                {
                    "sequence": trace_sequence,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "kind": kind,
                    "session_id": session_id,
                    "request_id": request_id,
                    "graph_id": graph_id,
                    **payload,
                }
            )

        model_trace = _ModelTraceAccumulator(record_trace)
        run_started = _runtime_event(
            "run_started",
            request_id=request_id,
            session_id=session_id,
            graph_id=graph_id,
            payload={
                "workspace_path": str(workspace.root),
                "status": "started",
                "intent": intent,
                "graph_kind": graph_kind,
            },
        )
        record_trace("lifecycle", {"event_type": "run_started", "payload": _json_safe(run_started.payload)})
        yield "frontend_event", run_started
        node_started = _runtime_event(
            "node_started",
            request_id=request_id,
            session_id=session_id,
            graph_id=graph_id,
            node_id=graph_id,
            node_label=node_label,
            payload={"workspace_path": str(workspace.root), "graph_kind": graph_kind},
        )
        record_trace(
            "lifecycle",
            {
                "event_type": "node_started",
                "node_id": graph_id,
                "node_label": node_label,
                "payload": _json_safe(node_started.payload),
            },
        )
        yield "frontend_event", node_started
        try:
            tool_env = self.tool_environment_builder.build(workspace_root=workspace.root, mode=graph_kind)
            if graph_kind == "manufacture":
                workflow = CreateAgentWorkflow(
                    tools=tool_env.tools,
                    model=self.model,
                    capability_inventory=tool_env.capability_inventory,
                ).compile(checkpointer=self.checkpointer)
            else:
                workflow = CreateAgentAssistWorkflow(
                    tools=tool_env.tools,
                    model=self.model,
                ).compile(checkpointer=self.checkpointer)
            config = {"configurable": {"thread_id": f"{session_id}:{graph_kind}"}}
            stream_input: Any
            if resume_payload is None:
                stream_input = {
                    "request": user_input,
                    "workspace_path": str(workspace.root),
                    "iteration": 0,
                    "done": False,
                    "messages": [HumanMessage(content=user_input)],
                }
            else:
                resume_update = _manufacture_resume_update(workspace=workspace, resume_payload=resume_payload) if graph_kind == "manufacture" else {}
                stream_input = Command(resume=resume_payload, update=resume_update or None)
                resumed = _runtime_event(
                    "runtime_resumed",
                    request_id=request_id,
                    session_id=session_id,
                    graph_id=graph_id,
                    payload=resume_payload,
                )
                record_trace("lifecycle", {"event_type": "runtime_resumed", "payload": _json_safe(resume_payload)})
                yield "frontend_event", resumed
            final_state: dict[str, Any] | None = None
            for stream_mode, chunk in workflow.stream(
                stream_input,
                config=config,
                stream_mode=["messages", "custom", "values"],
            ):
                interrupt_payload = extract_interrupt_payload(chunk)
                if interrupt_payload is not None:
                    interrupted = _runtime_event(
                        "interrupt_requested",
                        request_id=request_id,
                        session_id=session_id,
                        graph_id=graph_id,
                        payload=interrupt_payload,
                    )
                    record_trace(
                        "lifecycle",
                        {"event_type": "interrupt_requested", "payload": _json_safe(interrupt_payload)},
                    )
                    model_trace.flush()
                    yield "frontend_event", interrupted
                    return
                if stream_mode == "values" and isinstance(chunk, dict):
                    final_state = chunk
                    continue
                if stream_mode == "messages" and graph_kind == "manufacture":
                    model_trace.accept(chunk)
                if stream_mode == "custom" and graph_kind == "manufacture":
                    model_trace.flush()
                    if _is_model_cache_chunk(chunk):
                        record_trace("model_cache", _json_safe(chunk.get("payload") or {}))
                        continue
                    for record in _tool_trace_records(chunk):
                        record_trace("tool_call", record)
                yield stream_mode, chunk
            model_trace.flush()
            if not final_state:
                raise RuntimeError("create-agent workflow did not produce final state")
            if final_state.get("done"):
                message_completed = _runtime_event(
                    "model_message_completed",
                    request_id=request_id,
                    session_id=session_id,
                    graph_id=graph_id,
                    node_id=graph_id,
                    node_label=node_label,
                    payload={"content": str(final_state.get("final_answer") or "")},
                )
                record_trace(
                    "lifecycle",
                    {
                        "event_type": "model_message_completed",
                        "node_id": graph_id,
                        "node_label": node_label,
                        "payload": _json_safe(message_completed.payload),
                    },
                )
                yield "frontend_event", message_completed
                node_completed = _runtime_event(
                    "node_completed",
                    request_id=request_id,
                    session_id=session_id,
                    graph_id=graph_id,
                    node_id=graph_id,
                    node_label=node_label,
                    payload={"workspace_path": str(workspace.root), "status": "completed"},
                )
                record_trace(
                    "lifecycle",
                    {
                        "event_type": "node_completed",
                        "node_id": graph_id,
                        "node_label": node_label,
                        "payload": _json_safe(node_completed.payload),
                    },
                )
                yield "frontend_event", node_completed
                run_completed = _runtime_event(
                    "run_completed",
                    request_id=request_id,
                    session_id=session_id,
                    graph_id=graph_id,
                    payload={
                        "status": "completed",
                        "workspace_path": str(workspace.root),
                        "graph_kind": graph_kind,
                        "agent_session": {"session_id": session_id},
                    },
                )
                record_trace("lifecycle", {"event_type": "run_completed", "payload": _json_safe(run_completed.payload)})
                yield "frontend_event", run_completed
                return
            raise RuntimeError("create-agent workflow stopped before completion")
        except Exception as exc:
            model_trace.flush()
            node_failed = _runtime_event(
                "node_failed",
                request_id=request_id,
                session_id=session_id,
                graph_id=graph_id,
                node_id=graph_id,
                node_label=node_label,
                severity="error",
                payload={"message": f"{type(exc).__name__}: {exc}", "workspace_path": str(workspace.root)},
            )
            record_trace(
                "lifecycle",
                {
                    "event_type": "node_failed",
                    "node_id": graph_id,
                    "node_label": node_label,
                    "success": False,
                    "payload": _json_safe(node_failed.payload),
                },
            )
            yield "frontend_event", node_failed
            run_failed = _runtime_event(
                "run_failed",
                request_id=request_id,
                session_id=session_id,
                graph_id=graph_id,
                severity="error",
                message=f"{type(exc).__name__}: {exc}",
                payload={"message": f"{type(exc).__name__}: {exc}", "workspace_path": str(workspace.root)},
            )
            record_trace(
                "lifecycle",
                {
                    "event_type": "run_failed",
                    "success": False,
                    "message": f"{type(exc).__name__}: {exc}",
                    "payload": _json_safe(run_failed.payload),
                },
            )
            yield "frontend_event", run_failed


def _runtime_event(
    event_type: str,
    *,
    request_id: str,
    session_id: str,
    payload: dict[str, Any],
    graph_id: str = "create_agent_react",
    node_id: str | None = None,
    node_label: str | None = None,
    severity: str | None = None,
    message: str | None = None,
) -> FactoryFrontendEvent:
    return event(
        event_type,  # type: ignore[arg-type]
        request_id=request_id,
        session_id=session_id,
        mode="create_agent",
        graph_id=graph_id,
        producer_type=graph_id,
        node_id=node_id,
        node_label=node_label,
        node_kind=graph_id if node_id else None,
        severity=severity,
        message=message,
        payload=payload,
    )


def _manufacture_resume_update(*, workspace: CreateAgentWorkspace, resume_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(resume_payload, dict):
        return {}
    if not _is_publish_confirmation_resume(resume_payload):
        return {}
    decision = str(resume_payload.get("decision") or "").strip()
    input_text = _resume_input_text(resume_payload)
    if decision in {"publish", "approve"}:
        _write_publish_decision(workspace=workspace, decision="approve", input_text=input_text or "发布")
        message = "用户在发布确认面板选择了发布。下一步应调用 create_agent_publish。"
        normalized_decision = "approve"
    elif decision == "save_draft":
        _write_publish_decision(workspace=workspace, decision="pending", input_text=input_text or "保存草稿")
        message = "用户在发布确认面板选择了保存草稿。不要发布；向用户说明当前工作区已保留为草稿。"
        normalized_decision = "pending"
    else:
        _write_publish_decision(workspace=workspace, decision="pending", input_text=input_text)
        message = (
            "用户在发布确认面板输入了自然语言内容。不要发布；"
            f"把下面内容作为用户最新消息处理：{input_text}"
        )
        normalized_decision = "pending"
    return {
        "messages": [HumanMessage(content=message)],
        "publish_confirmation_response": {
            "decision": normalized_decision,
            "input_text": input_text,
            "instruction": (
                "User selected publish in the structured publish confirmation panel."
                if normalized_decision == "approve"
                else "Publish is still pending. Treat input_text as the user's latest message, not as publish approval."
            ),
        },
    }


def _is_publish_confirmation_resume(payload: dict[str, Any]) -> bool:
    payload_type = str(payload.get("type") or "").strip()
    if payload_type == "create_agent_publish_confirmation_result":
        return True
    decision = str(payload.get("decision") or "").strip()
    return decision == "approve" and ("input_text" in payload or "answer" in payload)


def _write_publish_decision(*, workspace: CreateAgentWorkspace, decision: str, input_text: str) -> None:
    validation = workspace.read_validation()
    workspace.write_publish_decision(
        CreateAgentPublishDecision(
            decision=decision,  # type: ignore[arg-type]
            input_text=input_text,
            package_fingerprint=package_fingerprint(workspace.root),
            validation_scope=validation.validation_scope if validation else "",
            validation_status=validation.status if validation else "",
        )
    )


def _resume_input_text(payload: dict[str, Any]) -> str:
    for key in ("input_text", "answer", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _message_stream_source(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, (list, tuple)) and len(chunk) >= 2 and isinstance(chunk[1], dict):
        metadata = chunk[1]
        return {
            "node": metadata.get("langgraph_node"),
            "step": metadata.get("langgraph_step"),
            "triggers": metadata.get("langgraph_triggers"),
        }
    return {}


class _ModelTraceAccumulator:
    def __init__(self, recorder: Any) -> None:
        self._recorder = recorder
        self._buffers: dict[str, dict[str, Any]] = {}

    def accept(self, chunk: Any) -> None:
        message, source = _message_stream_parts(chunk)
        if message is None:
            return
        message_type = message.__class__.__name__
        if message_type == "ToolMessage":
            self.flush()
            self._recorder("tool_message", _tool_message_trace_record(message, source))
            return
        key = _message_trace_key(source, message_type)
        buffer = self._buffers.setdefault(
            key,
            {
                "event_type": "model_message",
                "message_type": message_type,
                "source": source,
                "content": [],
                "tool_call_chunk_count": 0,
                "message_chunk_count": 0,
            },
        )
        buffer["message_chunk_count"] += 1
        content = getattr(message, "content", "")
        if isinstance(content, str) and content:
            buffer["content"].append(content)
        elif isinstance(content, list) and content:
            buffer["content"].append(_json_safe(content))
        tool_call_chunks = getattr(message, "tool_call_chunks", None)
        if tool_call_chunks:
            buffer["tool_call_chunk_count"] += len(tool_call_chunks)

    def flush(self) -> None:
        if not self._buffers:
            return
        buffers = list(self._buffers.values())
        self._buffers = {}
        for buffer in buffers:
            content_parts = buffer.pop("content", [])
            content = "".join(part for part in content_parts if isinstance(part, str))
            non_text_content = [part for part in content_parts if not isinstance(part, str)]
            payload = {
                **buffer,
                "content": content,
                "content_length": len(content),
            }
            if non_text_content:
                payload["non_text_content"] = non_text_content
            self._recorder("model_message", payload)


def _message_stream_parts(chunk: Any) -> tuple[Any | None, dict[str, Any]]:
    if not isinstance(chunk, (list, tuple)) or not chunk:
        return None, {}
    message = chunk[0]
    return message, _message_stream_source(chunk)


def _message_trace_key(source: dict[str, Any], message_type: str) -> str:
    return "|".join(
        [
            str(source.get("node") or ""),
            str(source.get("step") or ""),
            message_type,
        ]
    )


def _tool_message_trace_record(message: Any, source: dict[str, Any]) -> dict[str, Any]:
    content = getattr(message, "content", "")
    tool_call_id = getattr(message, "tool_call_id", None)
    name = getattr(message, "name", None)
    status = getattr(message, "status", None)
    return {
        "event_type": "tool_message",
        "message_type": message.__class__.__name__,
        "source": source,
        "tool_call_id": tool_call_id,
        "tool_id": name,
        "status": status,
        "content_length": len(content) if isinstance(content, str) else len(str(content)),
        "content_omitted": True,
    }


def _tool_trace_records(chunk: Any) -> list[dict[str, Any]]:
    if not isinstance(chunk, dict) or chunk.get("type") != "tool_activity":
        return []
    payload = chunk.get("payload")
    if not isinstance(payload, dict):
        return []
    events = payload.get("events")
    if not isinstance(events, list):
        return []
    records: list[dict[str, Any]] = []
    for item in events:
        if not isinstance(item, dict):
            continue
        event_type = str(item.get("event_type") or "")
        if event_type not in {"tool_proposed", "tool_completed", "tool_contract_invalid", "tool_failed"}:
            continue
        status = str(item.get("status") or "")
        records.append(
            {
                "event_type": event_type,
                "tool_id": item.get("tool_id"),
                "tool_call_id": item.get("tool_call_id"),
                "arguments": _json_safe(item.get("arguments") if isinstance(item.get("arguments"), dict) else {}),
                "status": status,
                "success": event_type in {"tool_completed", "tool_contract_invalid"} or status == "completed",
                "contract_status": str(item.get("contract_status") or ""),
                "execution_status": str(item.get("execution_status") or ""),
            }
        )
    return records


def _is_model_cache_chunk(chunk: Any) -> bool:
    return isinstance(chunk, dict) and chunk.get("type") == "create_agent_model_cache" and isinstance(chunk.get("payload"), dict)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
