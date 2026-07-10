from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
import shutil
import threading
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent_factory.create_agent.assist_workflow import CreateAgentAssistWorkflow
from agent_factory.create_agent.intent import classify_create_agent_intent
from agent_factory.create_agent.task_analysis import analyze_create_agent_task
from agent_factory.create_agent.tooling import CreateAgentToolEnvironmentBuilder
from agent_factory.create_agent.workflow import CreateAgentWorkflow
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer, json_safe as frontend_json_safe
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import extract_interrupt_payload
from agent_factory.factory_graph.session import build_factory_checkpointer_handle
from agent_factory.context_system.token_counter import context_window_payload
from agent_factory.model_pool.runtime_override import (
    RUNTIME_MAIN_MODEL_PROFILE_ID_KEY,
    main_model_profile_id_from_user_config,
)
from agent_factory.paths import factory_artifact_path, project_root
from agent_factory.runtime_attachments import (
    ATTACHMENT_INPUT_DIR,
    import_runtime_attachments,
    normalized_runtime_attachments,
    time_named_attachment_scope,
)
from agent_factory.runtime_kernel.persistence import delete_checkpoint_thread
from agent_factory.runtime_protocol.chat_parts import build_chat_turn_messages


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
        self._cancel_lock = threading.Lock()
        self._active_cancel_tokens: dict[str, threading.Event] = {}

    def cancel_active_requests(self, *, reason: str = "user_cancelled", request_id: str | None = None) -> int:
        del reason
        target = (request_id or "").strip()
        with self._cancel_lock:
            request_ids = [target] if target and target in self._active_cancel_tokens else list(self._active_cancel_tokens)
            for active_request_id in request_ids:
                self._active_cancel_tokens[active_request_id].set()
            return len(request_ids)

    def _register_cancel_token(self, request_id: str) -> threading.Event:
        token = threading.Event()
        with self._cancel_lock:
            self._active_cancel_tokens[request_id] = token
        return token

    def _forget_cancel_token(self, request_id: str, token: threading.Event) -> None:
        with self._cancel_lock:
            if self._active_cancel_tokens.get(request_id) is token:
                self._active_cancel_tokens.pop(request_id, None)

    def load_session_snapshot(self, session_id: str) -> dict[str, Any]:
        manufacture = self._checkpoint_snapshot(session_id=session_id, graph_kind="manufacture")
        assist = self._checkpoint_snapshot(session_id=session_id, graph_kind="assist")
        snapshot = manufacture or assist
        if snapshot is None:
            return {"session_id": session_id, "turn_count": 0, "turns": []}
        return snapshot

    def delete_session_artifacts(self, session_id: str) -> dict[str, Any]:
        workspace = CreateAgentWorkspace.for_session(session_id)
        self._active_graph_by_session.pop(session_id, None)
        deleted_checkpoint_count = sum(
            1
            for graph_kind in ("manufacture", "assist")
            if delete_checkpoint_thread(self.checkpointer, f"{session_id}:{graph_kind}")
        )
        workspace_deleted = _delete_create_agent_workspace(workspace.root)
        return {
            "session_id": session_id,
            "workspace_path": str(workspace.root),
            "workspace_deleted": workspace_deleted,
            "trace_deleted": workspace_deleted,
            "deleted_checkpoint_count": deleted_checkpoint_count,
        }

    def stream(
        self,
        *,
        user_input: str,
        session_id: str | None,
        request_id: str | None,
        attachments: Any = None,
        user_config: dict[str, Any] | None = None,
    ) -> CreateAgentStreamRun:
        resolved_session_id = session_id or uuid4().hex
        resolved_request_id = request_id or uuid4().hex
        workspace = CreateAgentWorkspace.for_session(resolved_session_id)
        attachment_scope = time_named_attachment_scope()
        attachment_result = import_runtime_attachments(
            user_input,
            attachments,
            storage_root=workspace.root / ".factory" / ATTACHMENT_INPUT_DIR / attachment_scope,
            runtime_path_root=f".factory/{ATTACHMENT_INPUT_DIR}/{attachment_scope}",
            base_dir=project_root(),
            scope=attachment_scope,
        )
        user_input = attachment_result.message
        runtime_main_model_profile_id = main_model_profile_id_from_user_config(user_config)
        intent = classify_create_agent_intent(
            user_input=user_input,
            workspace=workspace,
            model=self.model,
        )
        graph_kind = "manufacture" if intent.intent == "manufacture_agent" else "assist"
        self._active_graph_by_session[resolved_session_id] = graph_kind
        task_analysis = None
        if graph_kind == "manufacture":
            task_analysis = analyze_create_agent_task(user_input=user_input, model=self.model)
            workspace.initialize(user_input=user_input, task_analysis=task_analysis)
        else:
            workspace.root.mkdir(parents=True, exist_ok=True)
        return CreateAgentStreamRun(
            session_id=resolved_session_id,
            workspace=workspace,
            events=self._events(
                user_input=user_input,
                session_id=resolved_session_id,
                request_id=resolved_request_id,
                workspace=workspace,
                resume_payload=None,
                graph_kind=graph_kind,
                attachments=attachment_result.attachments,
                runtime_main_model_profile_id=runtime_main_model_profile_id,
                intent={
                    **intent.model_dump(mode="json"),
                    **({"task_analysis": task_analysis.model_dump(mode="json")} if task_analysis is not None else {}),
                },
            ),
        )

    def _checkpoint_snapshot(self, *, session_id: str, graph_kind: str) -> dict[str, Any] | None:
        values = self._checkpoint_values(thread_id=f"{session_id}:{graph_kind}")
        if not values:
            return None
        user_input = _checkpoint_user_input(values)
        final_answer = str(values.get("final_answer") or "").strip() or None
        if not user_input and not final_answer:
            return None
        now = datetime.now(UTC).isoformat()
        turn = {
            "index": 1,
            "created_at": now,
            "updated_at": now,
            "request_id": str(values.get("request_id") or "").strip() or None,
            "user_input": user_input,
            "attachments": normalized_runtime_attachments(values.get("runtime_attachments")),
            "final_answer": final_answer,
            "status": "completed" if values.get("done") else "running",
        }
        turn["messages"] = build_chat_turn_messages(
            index=turn["index"],
            created_at=turn["created_at"],
            updated_at=turn["updated_at"],
            user_input=turn.get("user_input"),
            attachments=turn.get("attachments"),
            final_answer=turn.get("final_answer"),
            status=turn.get("status"),
        )
        return {
            "session_id": session_id,
            "graph_kind": graph_kind,
            "workspace_path": str(CreateAgentWorkspace.for_session(session_id).root),
            "turn_count": 1,
            "turns": [turn],
        }

    def _checkpoint_values(self, *, thread_id: str) -> dict[str, Any]:
        get_tuple = getattr(self.checkpointer, "get_tuple", None)
        if not callable(get_tuple):
            return {}
        try:
            checkpoint_tuple = get_tuple({"configurable": {"thread_id": thread_id}})
        except Exception:
            return {}
        checkpoint = getattr(checkpoint_tuple, "checkpoint", None) if checkpoint_tuple is not None else None
        if not isinstance(checkpoint, dict):
            return {}
        values = checkpoint.get("channel_values") or checkpoint.get("values") or {}
        return dict(values) if isinstance(values, dict) else {}

    def resume_stream(
        self,
        *,
        session_id: str,
        resume_payload: dict[str, Any] | None,
        request_id: str | None,
    ) -> CreateAgentStreamRun:
        workspace = CreateAgentWorkspace.for_session(session_id)
        graph_kind = self._active_graph_by_session.get(session_id, "manufacture")
        resolved_request_id = request_id or uuid4().hex
        return CreateAgentStreamRun(
            session_id=session_id,
            workspace=workspace,
            events=self._events(
                user_input="",
                session_id=session_id,
                request_id=resolved_request_id,
                workspace=workspace,
                resume_payload=resume_payload or {},
                graph_kind=graph_kind,
                attachments=[],
                runtime_main_model_profile_id=None,
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
        attachments: list[dict[str, Any]],
        runtime_main_model_profile_id: str | None,
        intent: dict[str, Any] | None,
    ) -> Iterator[tuple[str, Any]]:
        request_id = request_id or uuid4().hex
        cancel_token = self._register_cancel_token(request_id)
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

        pending_events: list[FactoryFrontendEvent] = []

        def emit_frontend(item: FactoryFrontendEvent) -> None:
            pending_events.append(item)

        def drain_events() -> Iterator[tuple[str, FactoryFrontendEvent]]:
            while pending_events:
                yield "frontend_event", pending_events.pop(0)

        normalizer = RuntimeEventNormalizer(
            emit=emit_frontend,
            request_id=request_id,
            session_id=session_id,
            mode="create_agent",
            graph_id=graph_id,
            producer_type=graph_id,
        )
        model_trace = _ModelTraceAccumulator(record_trace)

        def emit_cancelled() -> Iterator[tuple[str, FactoryFrontendEvent]]:
            model_trace.flush()
            normalizer.complete_open_model_streams(reason="user_stopped")
            normalizer.runtime_event(
                "node_completed",
                node_id=graph_id,
                node_label=node_label,
                payload={"workspace_path": str(workspace.root), "status": "stopped", "graph_kind": graph_kind},
            )
            record_trace(
                "lifecycle",
                {
                    "event_type": "run_completed",
                    "payload": {
                        "status": "stopped",
                        "workspace_path": str(workspace.root),
                        "graph_kind": graph_kind,
                    },
                },
            )
            normalizer.emit_run_completed(
                {
                    "status": "stopped",
                    "workspace_path": str(workspace.root),
                    "graph_kind": graph_kind,
                    "agent_session": {"session_id": session_id},
                }
            )
            yield from drain_events()

        selected_pattern_payload = _selected_runtime_pattern_payload(intent)
        normalizer.emit_run_started(
            payload={
                "workspace_path": str(workspace.root),
                "status": "started",
                "intent": intent,
                "graph_kind": graph_kind,
                "attachment_count": len(attachments),
                **selected_pattern_payload,
            },
        )
        record_trace(
            "lifecycle",
            {
                "event_type": "run_started",
                "payload": {
                    "workspace_path": str(workspace.root),
                    "status": "started",
                    "intent": _json_safe(intent),
                    "graph_kind": graph_kind,
                    "attachment_count": len(attachments),
                    **_json_safe(selected_pattern_payload),
                },
            },
        )
        yield from drain_events()
        if cancel_token.is_set():
            yield from emit_cancelled()
            self._forget_cancel_token(request_id, cancel_token)
            return
        normalizer.runtime_event(
            "node_started",
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
                "payload": {"workspace_path": str(workspace.root), "graph_kind": graph_kind},
            },
        )
        yield from drain_events()
        try:
            if cancel_token.is_set():
                yield from emit_cancelled()
                return
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
                    "session_id": session_id,
                    "request_id": request_id,
                    "graph_kind": graph_kind,
                    "workspace_path": str(workspace.root),
                    "runtime_attachments": attachments,
                    RUNTIME_MAIN_MODEL_PROFILE_ID_KEY: runtime_main_model_profile_id or "",
                    "iteration": 0,
                    "done": False,
                    "messages": [HumanMessage(content=user_input)],
                }
            else:
                stream_input = Command(resume=resume_payload)
                normalizer.emit_runtime_resumed(resume_payload)
                record_trace("lifecycle", {"event_type": "runtime_resumed", "payload": _json_safe(resume_payload)})
                yield from drain_events()
            final_state: dict[str, Any] | None = None
            stream_iter = workflow.stream(
                stream_input,
                config=config,
                stream_mode=["messages", "custom", "values"],
            )
            try:
                for stream_mode, chunk in stream_iter:
                    if cancel_token.is_set():
                        yield from emit_cancelled()
                        return
                    interrupt_payload = extract_interrupt_payload(chunk)
                    if interrupt_payload is not None:
                        normalizer.emit_interrupt(frontend_json_safe(interrupt_payload))
                        record_trace(
                            "lifecycle",
                            {"event_type": "interrupt_requested", "payload": _json_safe(interrupt_payload)},
                        )
                        model_trace.flush()
                        yield from drain_events()
                        return
                    if stream_mode == "values" and isinstance(chunk, dict):
                        final_state = chunk
                        continue
                    if stream_mode == "messages" and graph_kind == "manufacture":
                        model_trace.accept(chunk)
                    if stream_mode == "custom" and graph_kind == "manufacture":
                        model_trace.flush()
                        if _is_model_cache_chunk(chunk):
                            cache_payload = _json_safe(chunk.get("payload") or {})
                            record_trace("model_cache", cache_payload)
                            node_id = str(cache_payload.get("node_id") or "create_agent_supervisor")
                            normalizer.runtime_event(
                                "model_cache_metrics",
                                node_id=node_id,
                                payload={
                                    **cache_payload,
                                    "session_id": session_id,
                                    "run_id": request_id,
                                    "agent_id": "create_agent",
                                    "agent_name": "制造 Agent",
                                },
                            )
                            normalizer.runtime_event(
                                "context_window_updated",
                                node_id=node_id,
                                payload=_context_window_payload_from_model_cache(cache_payload, node_id=node_id),
                            )
                            continue
                        for record in _tool_trace_records(chunk):
                            record_trace("tool_call", record)
                    normalizer.emit_stream_item(stream_mode, chunk, updates_payload_key="create_agent_update")
                    yield from drain_events()
            finally:
                close = getattr(stream_iter, "close", None)
                if callable(close):
                    close()
            model_trace.flush()
            if not final_state:
                raise RuntimeError("create-agent workflow did not produce final state")
            if final_state.get("done"):
                normalizer.complete_visible_assistant_output_from_text(
                    str(final_state.get("final_answer") or ""),
                    node_id=graph_id,
                    reason="run_completed",
                )
                record_trace(
                    "lifecycle",
                    {
                        "event_type": "model_message_completed",
                        "node_id": graph_id,
                        "node_label": node_label,
                        "payload": {"content_length": len(str(final_state.get("final_answer") or ""))},
                    },
                )
                normalizer.runtime_event(
                    "node_completed",
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
                        "payload": {"workspace_path": str(workspace.root), "status": "completed"},
                    },
                )
                normalizer.emit_run_completed(
                    payload={
                        "status": "completed",
                        "workspace_path": str(workspace.root),
                        "graph_kind": graph_kind,
                        "agent_session": {"session_id": session_id},
                        **(
                            {"publish_ready": final_state.get("publish_ready")}
                            if isinstance(final_state.get("publish_ready"), dict)
                            else {}
                        ),
                    },
                )
                record_trace(
                    "lifecycle",
                    {
                        "event_type": "run_completed",
                        "payload": {
                            "status": "completed",
                            "workspace_path": str(workspace.root),
                            "graph_kind": graph_kind,
                            "agent_session": {"session_id": session_id},
                            **(
                                {"publish_ready": _json_safe(final_state.get("publish_ready"))}
                                if isinstance(final_state.get("publish_ready"), dict)
                                else {}
                            ),
                        },
                    },
                )
                yield from drain_events()
                return
            raise RuntimeError("create-agent workflow stopped before completion")
        except Exception as exc:
            model_trace.flush()
            failure_payload = {"message": f"{type(exc).__name__}: {exc}", "workspace_path": str(workspace.root)}
            normalizer.runtime_event(
                "node_failed",
                node_id=graph_id,
                node_label=node_label,
                severity="error",
                payload=failure_payload,
            )
            record_trace(
                "lifecycle",
                {
                    "event_type": "node_failed",
                    "node_id": graph_id,
                    "node_label": node_label,
                    "success": False,
                    "payload": _json_safe(failure_payload),
                },
            )
            normalizer.emit_run_failed(exc)
            record_trace(
                "lifecycle",
                {
                    "event_type": "run_failed",
                    "success": False,
                    "message": f"{type(exc).__name__}: {exc}",
                    "payload": _json_safe(failure_payload),
                },
            )
            yield from drain_events()
        finally:
            self._forget_cancel_token(request_id, cancel_token)


def _checkpoint_user_input(values: dict[str, Any]) -> str | None:
    request = str(values.get("request") or "").strip()
    if request:
        return request
    messages = values.get("messages")
    if not isinstance(messages, list):
        return None
    for message in messages:
        if message.__class__.__name__ != "HumanMessage":
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _delete_create_agent_workspace(path: Path) -> bool:
    root = path.expanduser().resolve()
    workspace_root = factory_artifact_path("create_agent_workspaces").resolve()
    try:
        root.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f"create-agent workspace escapes workspace root: {root}") from exc
    if not root.exists():
        return False
    shutil.rmtree(root)
    return True


def _message_stream_source(chunk: Any) -> dict[str, Any]:
    if isinstance(chunk, (list, tuple)) and len(chunk) >= 2 and isinstance(chunk[1], dict):
        metadata = chunk[1]
        return {
            "node": metadata.get("langgraph_node"),
            "step": metadata.get("langgraph_step"),
            "triggers": metadata.get("langgraph_triggers"),
        }
    return {}


def _selected_runtime_pattern_payload(intent: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(intent, dict):
        return {}
    raw_analysis = intent.get("task_analysis")
    if not isinstance(raw_analysis, dict):
        return {}
    pattern_id = str(raw_analysis.get("selected_pattern_id") or "").strip()
    if not pattern_id:
        return {}
    return {
        "selected_runtime_pattern_id": pattern_id,
        "selected_runtime_pattern": {
            "pattern_id": pattern_id,
            "selection_reason": str(raw_analysis.get("selection_reason") or "").strip(),
            "requires_dynamic_plan": bool(raw_analysis.get("requires_dynamic_plan")),
            "intent_summary": str(raw_analysis.get("intent_summary") or "").strip(),
            "source": "create_agent_task_analysis",
        },
    }


class _ModelTraceAccumulator:
    def __init__(self, recorder: Any) -> None:
        self._recorder = recorder
        self._buffers: dict[str, dict[str, Any]] = {}

    def accept(self, chunk: Any) -> None:
        message, source = _message_stream_parts(chunk)
        if message is None:
            return
        message_type = message.__class__.__name__
        if message_type == "HumanMessage":
            self.flush()
            self._recorder("user_message", _user_message_trace_record(message, source))
            return
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


def _user_message_trace_record(message: Any, source: dict[str, Any]) -> dict[str, Any]:
    content = getattr(message, "content", "")
    additional_kwargs = getattr(message, "additional_kwargs", {})
    return {
        "event_type": "user_message",
        "message_type": message.__class__.__name__,
        "source": source,
        "message_source": "user",
        "message_kind": str(additional_kwargs.get("message_kind") or "user_message")
        if isinstance(additional_kwargs, dict)
        else "user_message",
        "interrupt_id": str(additional_kwargs.get("interrupt_id") or "")
        if isinstance(additional_kwargs, dict)
        else "",
        "interrupt_question": str(additional_kwargs.get("interrupt_question") or "")
        if isinstance(additional_kwargs, dict)
        else "",
        "content": content if isinstance(content, str) else _json_safe(content),
        "content_length": len(content) if isinstance(content, str) else 0,
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


def _context_window_payload_from_model_cache(payload: dict[str, Any], *, node_id: str) -> dict[str, Any]:
    provider_cache = payload.get("provider_cache") if isinstance(payload.get("provider_cache"), dict) else {}
    return context_window_payload(
        node_id=node_id,
        token_count=_positive_int(provider_cache.get("input_tokens")),
        token_count_method="provider_usage.input_tokens",
        compression_threshold_tokens=None,
        model_role="main",
        source="create_agent.model_cache_metrics",
    )


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
