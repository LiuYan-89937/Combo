from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent_factory.runtime_attachments import format_attachments_for_model


DEFAULT_AGENT_SYSTEM_PROMPT = "You are the generated Agent runtime model. Answer the user directly and concisely."
RUNTIME_REACT_PROTOCOL = (
    "Runtime ReAct protocol: use the conversation history as the source of truth. "
    "When tools are available and useful, call them with the model's native tool_call mechanism only. "
    "After a ToolMessage observation, continue from that observation and do not invent hidden tool results."
)
DYNAMIC_EVIDENCE_HEADER = (
    "Internal runtime evidence for this turn. Use it only when it is directly relevant. "
    "Do not quote, restate, or expose this evidence to the user unless the user explicitly asks for the underlying context:"
)


@dataclass(frozen=True, slots=True)
class ModelInputEnvelope:
    messages: list[Any]
    stable_prefix_digest: str
    dynamic_evidence_digest: str
    tool_surface_digest: str
    stable_system_chars: int
    dynamic_evidence_chars: int
    history_message_count: int
    tool_count: int

    def diagnostics(self) -> dict[str, Any]:
        return {
            "stable_prefix_digest": self.stable_prefix_digest,
            "dynamic_evidence_digest": self.dynamic_evidence_digest,
            "tool_surface_digest": self.tool_surface_digest,
            "stable_system_chars": self.stable_system_chars,
            "dynamic_evidence_chars": self.dynamic_evidence_chars,
            "history_message_count": self.history_message_count,
            "tool_count": self.tool_count,
        }


def build_runtime_model_input(
    *,
    state: Any,
    prompt_binding: dict[str, Any],
    messages: list[Any],
    tools: list[BaseTool],
    node_id: str | None = None,
) -> ModelInputEnvelope:
    stable_system = _stable_system_prompt(prompt_binding=prompt_binding)
    history_messages = _history_messages(state=state, messages=messages)
    dynamic_evidence = _dynamic_evidence_text(state=state, node_id=node_id)
    request_messages: list[Any] = [SystemMessage(content=stable_system), *history_messages]
    if dynamic_evidence:
        request_messages.append(
            SystemMessage(
                content=f"{DYNAMIC_EVIDENCE_HEADER}\n{dynamic_evidence}",
                additional_kwargs={
                    "kind": "runtime_dynamic_evidence",
                    "source": "runtime_context",
                    "node_id": node_id or "",
                },
            )
        )
    return ModelInputEnvelope(
        messages=request_messages,
        stable_prefix_digest=_digest_text(stable_system),
        dynamic_evidence_digest=_digest_text(dynamic_evidence),
        tool_surface_digest=_tool_surface_digest(tools),
        stable_system_chars=len(stable_system),
        dynamic_evidence_chars=len(dynamic_evidence),
        history_message_count=len(history_messages),
        tool_count=len(tools),
    )


def _stable_system_prompt(*, prompt_binding: dict[str, Any]) -> str:
    template = str(prompt_binding.get("template") or "").strip() or DEFAULT_AGENT_SYSTEM_PROMPT
    return "\n\n".join([template, RUNTIME_REACT_PROTOCOL])


def _history_messages(*, state: Any, messages: list[Any]) -> list[Any]:
    normalized = [message for message in messages if isinstance(message, BaseMessage)]
    if normalized:
        return normalized
    user_input = str(getattr(getattr(state, "conversation", None), "current_user_input", "") or "").strip()
    return [HumanMessage(content=user_input)] if user_input else []


def _dynamic_evidence_text(*, state: Any, node_id: str | None) -> str:
    plan_text = _plan_evidence_text(state)
    attachments_text = _runtime_attachments_text(state)
    model_context = getattr(getattr(state, "context", None), "model_context", {}) or {}
    frame = _turn_evidence_frame(model_context=model_context, node_id=node_id)
    if not isinstance(frame, dict):
        frame = model_context.get("llm_context_frame") if isinstance(model_context, dict) else None
    if not isinstance(frame, dict):
        return "\n\n".join(item for item in [plan_text, attachments_text] if item)
    text = str(frame.get("text") or "").strip()
    if text:
        return "\n\n".join(item for item in [plan_text, attachments_text, text] if item)
    items = frame.get("items")
    if not isinstance(items, list):
        return "\n\n".join(item for item in [plan_text, attachments_text] if item)
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(f"- {content}")
    context_text = "\n".join(lines)
    return "\n\n".join(item for item in [plan_text, attachments_text, context_text] if item)


def _runtime_attachments_text(state: Any) -> str:
    user_config = getattr(getattr(state, "runtime_config", None), "user_config", {}) or {}
    if not isinstance(user_config, dict):
        return ""
    return format_attachments_for_model(user_config.get("attachments"))


def _plan_evidence_text(state: Any) -> str:
    plan = getattr(state, "plan", None)
    if plan is None or getattr(plan, "status", "empty") == "empty":
        return ""
    lines = [
        "Current dynamic plan state:",
        f"- Goal: {getattr(plan, 'goal', '')}",
        f"- Status: {getattr(plan, 'status', '')}",
        f"- Current step: {getattr(plan, 'current_step_id', None) or 'none'}",
    ]
    for step in list(getattr(plan, "steps", []) or [])[:12]:
        lines.append(
            "- "
            + f"{getattr(step, 'step_id', '')}: {getattr(step, 'status', '')}; "
            + f"{getattr(step, 'title', '')}; {getattr(step, 'objective', '')}"
        )
        result = getattr(step, "result_summary", None)
        if result:
            lines.append(f"  result: {result}")
    return "\n".join(line for line in lines if line.strip())


def _turn_evidence_frame(*, model_context: dict[str, Any], node_id: str | None) -> dict[str, Any] | None:
    evidence = model_context.get("runtime_turn_evidence")
    if not isinstance(evidence, dict):
        return None
    entries = evidence.get("entries")
    if not isinstance(entries, dict):
        return None
    candidates = [str(node_id or ""), "_default"]
    for key in candidates:
        entry = entries.get(key)
        if not isinstance(entry, dict):
            continue
        frame = entry.get("frame")
        if isinstance(frame, dict):
            return frame
    return None


def _tool_surface_digest(tools: list[BaseTool]) -> str:
    payload = []
    for tool in sorted(tools, key=lambda item: str(getattr(item, "name", ""))):
        payload.append(
            {
                "name": str(getattr(tool, "name", "") or ""),
                "description": str(getattr(tool, "description", "") or ""),
                "args": _tool_args_payload(tool),
            }
        )
    return _digest_json(payload)


def _tool_args_payload(tool: BaseTool) -> Any:
    args = getattr(tool, "args", None)
    if args is not None:
        return _json_safe(args)
    schema = getattr(tool, "args_schema", None)
    if schema is not None and hasattr(schema, "model_json_schema"):
        try:
            return schema.model_json_schema()
        except Exception:
            return str(schema)
    return {}


def _digest_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()[:16]


def _digest_json(value: Any) -> str:
    return sha256(json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
