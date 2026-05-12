from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable
import uuid

from langchain_core.messages import BaseMessage, ToolMessage

from agent_factory.factory_graph.chat_graph import FACTORY_CHAT_TOOLS_NODE
from agent_factory.factory_graph.constants import STAGE_IDS
from agent_factory.factory_graph.frontend_bridge.protocol import (
    FactoryFrontendEvent,
    FactoryFrontendEventType,
    FactoryMode,
    event,
)
from agent_factory.factory_graph.graph import FACTORY_TOOLS_NODE


Emit = Callable[[FactoryFrontendEvent], None]


@dataclass(slots=True)
class ModelStreamState:
    stream_id: str
    node_id: str
    span_id: str
    parent_span_id: str | None
    content: str = ""
    completed: bool = False


@dataclass(slots=True)
class RuntimeEventNormalizer:
    emit: Emit
    request_id: str | None
    session_id: str | None
    mode: FactoryMode
    graph_id: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    sequence: int = 0
    run_span_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    stage_spans: dict[str, str] = field(default_factory=dict)
    node_spans: dict[str, str] = field(default_factory=dict)
    started_nodes: set[str] = field(default_factory=set)
    completed_nodes: set[str] = field(default_factory=set)
    model_streams: dict[str, ModelStreamState] = field(default_factory=dict)
    current_stage_id: str | None = None

    def runtime_event(
        self,
        event_type: FactoryFrontendEventType,
        *,
        node_id: str | None = None,
        stage_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> FactoryFrontendEvent:
        self.sequence += 1
        item = event(
            event_type,
            request_id=self.request_id,
            run_id=self.run_id,
            session_id=self.session_id,
            mode=self.mode,
            graph_id=self.graph_id,
            node_id=node_id,
            stage_id=stage_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            sequence=self.sequence,
            timestamp=datetime.now(UTC).isoformat(),
            message=message,
            payload=payload,
        )
        self.emit(item)
        return item

    def emit_run_started(self, payload: dict[str, Any]) -> None:
        self.runtime_event(
            "run_started",
            span_id=self.run_span_id,
            payload={"run_id": self.run_id, **payload},
        )

    def emit_run_completed(self, payload: dict[str, Any]) -> None:
        self.complete_open_model_streams(reason="run_completed")
        self.runtime_event(
            "trace_snapshot",
            span_id=self.run_span_id,
            payload={
                "run_id": self.run_id,
                "stage_spans": self.stage_spans,
                "node_spans": self.node_spans,
                "sequence": self.sequence,
            },
        )
        self.runtime_event("run_completed", span_id=self.run_span_id, payload=payload)

    def emit_run_failed(self, exc: Exception) -> None:
        payload = {"where": "runtime_stream", "error_type": type(exc).__name__, "message": str(exc)}
        self.complete_open_model_streams(reason="run_failed")
        self.runtime_event("run_failed", span_id=self.run_span_id, message=f"{type(exc).__name__}: {exc}", payload=payload)

    def emit_update(self, node_id: str, patch: dict[str, Any]) -> None:
        stage_id = _stage_id_from_patch(patch) or self.current_stage_id
        node_span_id = self._node_span(node_id, stage_id)
        if stage_id:
            self._ensure_stage_started(stage_id)
        if node_id not in self.started_nodes:
            self._emit_node_started(node_id, stage_id, {"node_id": node_id, "source": "updates_default"})
        self.runtime_event(
            "debug_patch",
            node_id=node_id,
            stage_id=stage_id,
            span_id=node_span_id,
            parent_span_id=self._stage_span_or_run(stage_id),
            payload={"patch": patch},
        )
        self.emit_model_activity_from_patch(node_id, stage_id, patch)
        self._emit_tool_proposals(node_id, stage_id, node_span_id, patch)
        self._emit_tool_observations(node_id, stage_id, node_span_id, patch)
        for item in patch.get("stage_log", []) or []:
            item_stage_id = str(item.get("stage_id") or stage_id or "")
            if item_stage_id:
                self._ensure_stage_started(item_stage_id)
            self.runtime_event(
                "stage_completed",
                node_id=node_id,
                stage_id=item_stage_id or None,
                span_id=self._stage_span_or_run(item_stage_id or None),
                parent_span_id=self.run_span_id,
                payload=item,
            )
        if node_id not in self.completed_nodes:
            self._emit_node_completed(node_id, stage_id, {"node_id": node_id, "source": "updates_default"})

    def emit_debug_event(self, chunk: Any) -> None:
        if not isinstance(chunk, dict):
            return
        payload = chunk.get("payload") or {}
        debug_type = chunk.get("type")
        if debug_type == "task":
            node_id = str(payload.get("name") or "")
            if node_id:
                stage_id = node_id if node_id in STAGE_IDS else self.current_stage_id
                if stage_id:
                    self._ensure_stage_started(stage_id)
                self._emit_node_started(node_id, stage_id, {"task": json_safe(payload), "step": chunk.get("step")})
        elif debug_type == "task_result":
            node_id = str(payload.get("name") or "")
            if not node_id:
                return
            stage_id = node_id if node_id in STAGE_IDS else self.current_stage_id
            if payload.get("error"):
                self.runtime_event(
                    "node_failed",
                    node_id=node_id,
                    stage_id=stage_id,
                    span_id=self._node_span(node_id, stage_id),
                    parent_span_id=self._stage_span_or_run(stage_id),
                    payload={"task": json_safe(payload), "step": chunk.get("step")},
                )
            else:
                self._emit_node_completed(node_id, stage_id, {"task": json_safe(payload), "step": chunk.get("step")})

    def emit_custom_event(self, chunk: Any) -> None:
        if not isinstance(chunk, dict):
            return
        if chunk.get("type") != "model_activity":
            self.runtime_event(
                "debug_patch",
                span_id=self.run_span_id,
                payload={"custom": json_safe(chunk)},
            )
            return
        payload = chunk.get("payload")
        if not isinstance(payload, dict):
            return
        event_type = str(payload.get("event_type") or "")
        if event_type not in {"model_call_started", "model_call_completed", "model_call_failed"}:
            return
        span_id = str(payload.get("span_id") or uuid.uuid4().hex)
        self.runtime_event(
            event_type,  # type: ignore[arg-type]
            stage_id=self.current_stage_id,
            span_id=span_id,
            parent_span_id=self.run_span_id,
            payload={key: value for key, value in json_safe(payload).items() if key not in {"event_type", "span_id"}},
        )

    def emit_message_chunk(self, chunk: Any) -> None:
        try:
            message_chunk, metadata = chunk
        except Exception:
            return
        if "nostream" in set(metadata.get("tags", [])):
            return
        node_id = str(metadata.get("langgraph_node") or "")
        if node_id in {FACTORY_TOOLS_NODE, FACTORY_CHAT_TOOLS_NODE}:
            return
        if isinstance(message_chunk, ToolMessage):
            return
        content = _content_to_text(getattr(message_chunk, "content", ""))
        if not content:
            return
        stream = self._model_stream(node_id or "model")
        stream.content += content
        self.runtime_event(
            "model_stream_delta",
            node_id=node_id,
            stage_id=self.current_stage_id,
            span_id=stream.span_id,
            parent_span_id=stream.parent_span_id,
            payload={"stream_id": stream.stream_id, "delta": content},
        )

    def emit_model_activity_from_patch(self, node_id: str, stage_id: str | None, patch: dict[str, Any]) -> None:
        for item in patch.get("model_activity", []) or []:
            if not isinstance(item, dict):
                continue
            event_type = str(item.get("event_type") or "")
            if event_type not in {"model_call_started", "model_call_completed", "model_call_failed"}:
                continue
            span_id = str(item.get("span_id") or uuid.uuid4().hex)
            payload = {key: value for key, value in item.items() if key not in {"event_type", "span_id"}}
            self.runtime_event(
                event_type,  # type: ignore[arg-type]
                node_id=node_id,
                stage_id=stage_id,
                span_id=span_id,
                parent_span_id=self._node_span(node_id, stage_id),
                payload=payload,
            )

    def emit_interrupt(self, payload: Any) -> None:
        self.complete_open_model_streams(reason="runtime_paused")
        safe_payload = payload if isinstance(payload, dict) else {"value": payload}
        interrupt_type = safe_payload.get("type") if isinstance(safe_payload, dict) else None
        interrupt_span_id = uuid.uuid4().hex
        if interrupt_type == "tool_approval":
            requests = safe_payload.get("requests", []) or []
            for request in requests:
                tool_span_id = uuid.uuid4().hex
                self.runtime_event(
                    "tool_call_proposed",
                    span_id=tool_span_id,
                    parent_span_id=self.run_span_id,
                    payload=request,
                )
            self.runtime_event(
                "tool_approval_requested",
                span_id=interrupt_span_id,
                parent_span_id=self.run_span_id,
                payload=safe_payload,
            )
        elif interrupt_type == "resource_input":
            self.runtime_event(
                "resource_input_requested",
                span_id=interrupt_span_id,
                parent_span_id=self.run_span_id,
                payload=safe_payload,
            )
        self.runtime_event(
            "interrupt_requested",
            span_id=interrupt_span_id,
            parent_span_id=self.run_span_id,
            payload=safe_payload,
        )
        self.runtime_event(
            "runtime_paused",
            span_id=self.run_span_id,
            payload={"reason": interrupt_type or "interrupt"},
        )

    def emit_runtime_resumed(self, payload: dict[str, Any]) -> None:
        if "approved" in payload or "action" in payload:
            self.runtime_event("tool_approval_resolved", span_id=self.run_span_id, payload=payload)
        self.runtime_event("runtime_resumed", span_id=self.run_span_id, payload=payload)

    def complete_open_model_streams(self, *, reason: str) -> None:
        for stream in list(self.model_streams.values()):
            if stream.completed:
                continue
            stream.completed = True
            self.runtime_event(
                "model_message_completed",
                node_id=stream.node_id,
                stage_id=self.current_stage_id,
                span_id=stream.span_id,
                parent_span_id=stream.parent_span_id,
                payload={
                    "stream_id": stream.stream_id,
                    "content": stream.content,
                    "completion_reason": reason,
                    "completion_inferred": True,
                },
            )

    def _ensure_stage_started(self, stage_id: str) -> str:
        self.current_stage_id = stage_id
        if stage_id not in self.stage_spans:
            span_id = uuid.uuid4().hex
            self.stage_spans[stage_id] = span_id
            self.runtime_event(
                "stage_started",
                stage_id=stage_id,
                span_id=span_id,
                parent_span_id=self.run_span_id,
                payload={"stage_id": stage_id},
            )
        return self.stage_spans[stage_id]

    def _node_span(self, node_id: str, stage_id: str | None) -> str:
        key = node_id
        if key not in self.node_spans:
            self.node_spans[key] = uuid.uuid4().hex
        return self.node_spans[key]

    def _emit_node_started(self, node_id: str, stage_id: str | None, payload: dict[str, Any]) -> None:
        self.started_nodes.add(node_id)
        self.runtime_event(
            "node_started",
            node_id=node_id,
            stage_id=stage_id,
            span_id=self._node_span(node_id, stage_id),
            parent_span_id=self._stage_span_or_run(stage_id),
            payload=payload,
        )

    def _emit_node_completed(self, node_id: str, stage_id: str | None, payload: dict[str, Any]) -> None:
        self.completed_nodes.add(node_id)
        self.runtime_event(
            "node_completed",
            node_id=node_id,
            stage_id=stage_id,
            span_id=self._node_span(node_id, stage_id),
            parent_span_id=self._stage_span_or_run(stage_id),
            payload=payload,
        )

    def _stage_span_or_run(self, stage_id: str | None) -> str:
        if not stage_id:
            return self.run_span_id
        return self.stage_spans.get(stage_id) or self._ensure_stage_started(stage_id)

    def _model_stream(self, node_id: str) -> ModelStreamState:
        if node_id not in self.model_streams or self.model_streams[node_id].completed:
            node_span = self._node_span(node_id, self.current_stage_id)
            stream = ModelStreamState(
                stream_id=uuid.uuid4().hex,
                node_id=node_id,
                span_id=uuid.uuid4().hex,
                parent_span_id=node_span,
            )
            self.model_streams[node_id] = stream
            self.runtime_event(
                "model_call_started",
                node_id=node_id,
                stage_id=self.current_stage_id,
                span_id=stream.span_id,
                parent_span_id=node_span,
                payload={"stream_id": stream.stream_id},
            )
        return self.model_streams[node_id]

    def _emit_tool_observations(self, node_id: str, stage_id: str | None, parent_span_id: str, patch: dict[str, Any]) -> None:
        for message in patch.get("messages", []) or []:
            if message.get("type") != "ToolMessage":
                continue
            tool_span_id = uuid.uuid4().hex
            payload = {"message": message}
            self.runtime_event(
                "tool_call_completed",
                node_id=node_id,
                stage_id=stage_id,
                span_id=tool_span_id,
                parent_span_id=parent_span_id,
                payload=payload,
            )
            self.runtime_event(
                "tool_observation_available",
                node_id=node_id,
                stage_id=stage_id,
                span_id=tool_span_id,
                parent_span_id=parent_span_id,
                payload=payload,
            )
        resource_plan = patch.get("resource_condition_plan") or {}
        for item in resource_plan.get("check_results", []) or []:
            tool_span_id = uuid.uuid4().hex
            payload = {"resource_check": item}
            self.runtime_event(
                "tool_call_completed",
                node_id=node_id,
                stage_id=stage_id,
                span_id=tool_span_id,
                parent_span_id=parent_span_id,
                payload=payload,
            )

    def _emit_tool_proposals(self, node_id: str, stage_id: str | None, parent_span_id: str, patch: dict[str, Any]) -> None:
        for message in patch.get("messages", []) or []:
            if message.get("type") != "AIMessage":
                continue
            for tool_call in message.get("tool_calls", []) or []:
                if not isinstance(tool_call, dict):
                    continue
                tool_span_id = uuid.uuid4().hex
                payload = {
                    "tool_call_id": tool_call.get("id"),
                    "tool_name": tool_call.get("name"),
                    "arguments": tool_call.get("args") or {},
                    "source": "ai_tool_call",
                }
                self.runtime_event(
                    "tool_call_proposed",
                    node_id=node_id,
                    stage_id=stage_id,
                    span_id=tool_span_id,
                    parent_span_id=parent_span_id,
                    payload=payload,
                )
                self.runtime_event(
                    "tool_call_started",
                    node_id=node_id,
                    stage_id=stage_id,
                    span_id=tool_span_id,
                    parent_span_id=parent_span_id,
                    payload=payload,
                )


def _stage_id_from_patch(patch: dict[str, Any]) -> str | None:
    if patch.get("current_stage"):
        return str(patch.get("current_stage"))
    stage_log = patch.get("stage_log") or []
    if stage_log:
        return str(stage_log[-1].get("stage_id") or "")
    return None


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "".join(parts)
    return str(content) if content else ""


def json_safe(value: Any) -> Any:
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
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
