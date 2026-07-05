from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_factory.collaboration_system.store import CollaborationStore
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import visible_message_part_content


@dataclass(slots=True)
class CollaborationWorkerEventRecorder:
    store: CollaborationStore
    collaboration_id: str
    task_id: str
    package_id: str
    max_output_chars: int = 900
    _seen_progress_keys: set[str] = field(default_factory=set)

    def accept(self, item: FactoryFrontendEvent) -> None:
        content = _message_for_event(item, max_output_chars=self.max_output_chars)
        if not content:
            return
        progress_key = _progress_key(item, content)
        if progress_key:
            if progress_key in self._seen_progress_keys:
                return
            self._seen_progress_keys.add(progress_key)
        self.store.record_message(
            self.collaboration_id,
            speaker_type="worker_agent" if item.event_type.startswith("message_") else "system",
            speaker_package_id=self.package_id,
            message_kind=_message_kind(item),
            content=content,
            task_id=self.task_id,
            event_ref=item.event_id,
        )


def _message_for_event(item: FactoryFrontendEvent, *, max_output_chars: int) -> str | None:
    event_type = item.event_type
    payload = item.payload if isinstance(item.payload, dict) else {}
    if event_type == "plan_updated":
        summary = _compact(payload.get("summary") or payload.get("title") or payload.get("message") or "")
        return f"计划已更新。{summary}" if summary else "计划已更新。"
    if event_type in {"node_started", "node_progress", "node_completed", "node_failed"}:
        return _node_message(item)
    if event_type in {"tool_call_started", "tool_call_completed", "tool_call_failed"}:
        return _tool_message(item)
    if event_type == "tool_approval_requested":
        return _tool_approval_message(item)
    if event_type == "message_part_completed" and payload.get("part_type") == "reasoning":
        reasoning = visible_message_part_content(item)
        if not reasoning:
            return None
        return "思考摘要：\n" + _truncate(reasoning, max_output_chars)
    if event_type == "message_part_completed" and payload.get("part_type") == "text":
        content = visible_message_part_content(item)
        if not content:
            return None
        return "阶段输出：\n" + _truncate(content, max_output_chars)
    return None


def _tool_approval_message(item: FactoryFrontendEvent) -> str:
    payload = item.payload if isinstance(item.payload, dict) else {}
    requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
    names = [
        _compact(request.get("tool_name") or request.get("tool_id") or request.get("name") or "")
        for request in requests
        if isinstance(request, dict)
    ]
    clean_names = [name for name in names if name]
    if clean_names:
        return "工具调用等待审批：" + "、".join(clean_names)
    return "工具调用等待审批。"


def _node_message(item: FactoryFrontendEvent) -> str | None:
    label = _node_label(item)
    detail = _compact(item.message or item.payload.get("message") or item.payload.get("status") or "")
    if item.event_type == "node_started":
        return f"开始：{label}"
    if item.event_type == "node_progress":
        return f"进度：{label}" + (f" - {detail}" if detail else "")
    if item.event_type == "node_completed":
        return f"完成：{label}"
    if item.event_type == "node_failed":
        return f"失败：{label}" + (f" - {detail}" if detail else "")
    return None


def _tool_message(item: FactoryFrontendEvent) -> str | None:
    payload = item.payload if isinstance(item.payload, dict) else {}
    name = _compact(payload.get("tool_name") or payload.get("tool_id") or "tool")
    if item.event_type == "tool_call_started":
        return f"工具开始：{name}"
    if item.event_type == "tool_call_completed":
        return f"工具完成：{name}"
    if item.event_type == "tool_call_failed":
        detail = _compact(item.message or payload.get("error") or payload.get("message") or "")
        return f"工具失败：{name}" + (f" - {detail}" if detail else "")
    return None


def _message_kind(item: FactoryFrontendEvent) -> str:
    if item.event_type.startswith("tool_call_"):
        return "tool"
    if item.event_type == "tool_approval_requested":
        return "approval"
    if item.event_type.startswith("message_"):
        return "worker_output"
    if item.event_type == "plan_updated":
        return "plan"
    return "progress"


def _progress_key(item: FactoryFrontendEvent, content: str) -> str | None:
    if item.event_type not in {"node_progress", "message_part_completed"}:
        return None
    return f"{item.event_type}:{item.node_id or ''}:{content}"


def _node_label(item: FactoryFrontendEvent) -> str:
    return _compact(item.node_label or item.node_id or item.stage_id or "worker")


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split())


def _truncate(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"
