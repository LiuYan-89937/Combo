from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from agent_factory.runtime_attachments import format_attachments_for_model
from agent_factory.runtime_defaults import (
    DEFAULT_BUILTIN_ALLOW_EXTERNAL_PATHS,
    DEFAULT_BUILTIN_WORKSPACE_ROOT,
)
from agent_factory.runtime_kernel.planning import is_plan_and_execute_pattern_id


DEFAULT_AGENT_SYSTEM_PROMPT = "You are the generated Agent runtime model. Answer the user directly and concisely."
RUNTIME_REACT_PROTOCOL = (
    "Runtime ReAct protocol: use the conversation history as the source of truth. "
    "When tools are available and useful, call them with the model's native tool_call mechanism only. "
    "After a ToolMessage observation, continue from that observation and do not invent hidden tool results."
)
EXECUTOR_TOOL_POLICY = "Executor tool policy: execute the current plan step with package/domain tools first."
DYNAMIC_EVIDENCE_HEADER = (
    "Internal runtime evidence for this turn. Use it only when it is directly relevant. "
    "Do not quote, restate, or expose this evidence to the user unless the user explicitly asks for the underlying context:"
)
PLAN_EVIDENCE_MAX_STEPS = 12
PLAN_RESULT_SUMMARY_MAX_CHARS = 900
PLAN_EVIDENCE_VALUE_MAX_CHARS = 240
EXECUTOR_RECENT_TOOL_EXCHANGE_COUNT = 1
PLAN_EXECUTE_EXECUTOR_NODE_ID = "executor"
PLAN_EXECUTE_FINAL_ANSWER_NODE_ID = "final_answer"
PLAN_EXECUTE_PROJECTED_HISTORY_NODES = frozenset(
    {
        PLAN_EXECUTE_EXECUTOR_NODE_ID,
        PLAN_EXECUTE_FINAL_ANSWER_NODE_ID,
    }
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
    stable_system = _stable_system_prompt(prompt_binding=prompt_binding, state=state, node_id=node_id)
    history_messages = _history_messages(state=state, messages=messages, node_id=node_id)
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


def _stable_system_prompt(*, prompt_binding: dict[str, Any], state: Any, node_id: str | None = None) -> str:
    template = str(prompt_binding.get("template") or "").strip() or DEFAULT_AGENT_SYSTEM_PROMPT
    parts = [template]
    if node_id == PLAN_EXECUTE_EXECUTOR_NODE_ID:
        parts.append(_executor_tool_policy(state))
    parts.append(RUNTIME_REACT_PROTOCOL)
    return "\n\n".join(parts)


def _executor_tool_policy(state: Any) -> str:
    workspace_root = _builtin_workspace_root(state)
    allow_external = _builtin_allow_external_paths(state)
    boundary = (
        "External absolute paths are enabled, but prefer workspace paths unless the task explicitly needs an external path."
        if allow_external
        else (
            f"Filesystem and process tools are bounded to workspace root {workspace_root}. "
            "Use relative paths, or absolute paths under that root. "
            "Do not use /tmp, host paths, or arbitrary absolute paths."
        )
    )
    return (
        f"{EXECUTOR_TOOL_POLICY} "
        "glob, ls, and read may be used to inspect workspace files. "
        "Call bash, write, edit, or multi_edit only when the available package/runtime tools cannot accomplish "
        "the current plan step; when doing so, include fallback_reason in the tool arguments explaining the gap. "
        f"{boundary} Generated files should be written under the workspace root, for example "
        f"output/report.md or {workspace_root.rstrip('/')}/output/report.md."
    )


def _builtin_workspace_root(state: Any) -> str:
    session_config = getattr(getattr(state, "runtime_config", None), "session_config", {}) or {}
    if not isinstance(session_config, dict):
        return DEFAULT_BUILTIN_WORKSPACE_ROOT
    value = str(session_config.get("builtin_workspace_root") or DEFAULT_BUILTIN_WORKSPACE_ROOT).strip()
    return value or DEFAULT_BUILTIN_WORKSPACE_ROOT


def _builtin_allow_external_paths(state: Any) -> bool:
    session_config = getattr(getattr(state, "runtime_config", None), "session_config", {}) or {}
    if not isinstance(session_config, dict):
        return DEFAULT_BUILTIN_ALLOW_EXTERNAL_PATHS
    return bool(session_config.get("builtin_allow_external_paths", DEFAULT_BUILTIN_ALLOW_EXTERNAL_PATHS))


def _history_messages(*, state: Any, messages: list[Any], node_id: str | None) -> list[Any]:
    normalized = [message for message in messages if isinstance(message, BaseMessage)]
    if normalized and _uses_plan_and_execute_projection(state=state, node_id=node_id):
        return _plan_and_execute_history_messages(state=state, messages=normalized, node_id=node_id)
    if normalized:
        return normalized
    user_input = str(getattr(getattr(state, "conversation", None), "current_user_input", "") or "").strip()
    return [HumanMessage(content=user_input)] if user_input else []


def _uses_plan_and_execute_projection(*, state: Any, node_id: str | None) -> bool:
    if not is_plan_and_execute_pattern_id(getattr(getattr(state, "run", None), "pattern_id", None)):
        return False
    return node_id in PLAN_EXECUTE_PROJECTED_HISTORY_NODES


def _plan_and_execute_history_messages(*, state: Any, messages: list[BaseMessage], node_id: str | None) -> list[BaseMessage]:
    user_message = _current_user_message(state=state, messages=messages)
    if node_id == PLAN_EXECUTE_FINAL_ANSWER_NODE_ID:
        return [user_message] if user_message is not None else []
    if node_id != PLAN_EXECUTE_EXECUTOR_NODE_ID:
        return messages
    projected: list[BaseMessage] = []
    if user_message is not None:
        projected.append(user_message)
    projected.extend(
        _recent_tool_exchanges(
            messages=messages,
            origin_node_id=PLAN_EXECUTE_EXECUTOR_NODE_ID,
            limit=EXECUTOR_RECENT_TOOL_EXCHANGE_COUNT,
        )
    )
    return projected or messages[-1:]


def _current_user_message(*, state: Any, messages: list[BaseMessage]) -> HumanMessage | None:
    current_input = str(getattr(getattr(state, "conversation", None), "current_user_input", "") or "").strip()
    for message in reversed(messages):
        if not isinstance(message, HumanMessage):
            continue
        if not current_input:
            return message
        if _message_text(message).strip() == current_input:
            return message
    if current_input:
        return HumanMessage(content=current_input)
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message
    return None


def _recent_tool_exchanges(*, messages: list[BaseMessage], origin_node_id: str, limit: int) -> list[BaseMessage]:
    exchanges: list[list[BaseMessage]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if not _is_ai_tool_call_from_node(message, origin_node_id=origin_node_id):
            index += 1
            continue
        tool_call_ids = _tool_call_ids(message)
        exchange: list[BaseMessage] = [message]
        cursor = index + 1
        pending = set(tool_call_ids)
        while cursor < len(messages):
            candidate = messages[cursor]
            if not isinstance(candidate, ToolMessage):
                break
            if not pending or str(getattr(candidate, "tool_call_id", "") or "") in pending:
                exchange.append(candidate)
                pending.discard(str(getattr(candidate, "tool_call_id", "") or ""))
            cursor += 1
        if tool_call_ids and not pending:
            exchanges.append(exchange)
        index = max(cursor, index + 1)
    selected = exchanges[-max(1, limit):]
    return [message for exchange in selected for message in exchange]


def _is_ai_tool_call_from_node(message: BaseMessage, *, origin_node_id: str) -> bool:
    if not isinstance(message, AIMessage):
        return False
    if not _tool_call_ids(message):
        return False
    metadata = dict(getattr(message, "additional_kwargs", {}) or {})
    return str(metadata.get("agent_factory_origin_node_id") or "") == origin_node_id


def _tool_call_ids(message: BaseMessage) -> list[str]:
    if not isinstance(message, AIMessage):
        return []
    ids: list[str] = []
    for call in list(getattr(message, "tool_calls", None) or []):
        if not isinstance(call, dict):
            continue
        call_id = str(call.get("id") or call.get("tool_call_id") or "").strip()
        if call_id:
            ids.append(call_id)
    for call in list(getattr(message, "invalid_tool_calls", None) or []):
        if not isinstance(call, dict):
            continue
        call_id = str(call.get("id") or call.get("tool_call_id") or "").strip()
        if call_id:
            ids.append(call_id)
    return ids


def _dynamic_evidence_text(*, state: Any, node_id: str | None) -> str:
    plan_text = _plan_evidence_text(state)
    attachments_text = _runtime_attachments_text(state)
    model_context = getattr(getattr(state, "context", None), "model_context", {}) or {}
    frame = _turn_evidence_frame(model_context=model_context, node_id=node_id)
    if not isinstance(frame, dict) and isinstance(model_context, dict):
        frame = _matching_node_frame(model_context.get("llm_context_frame"), node_id=node_id)
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
    current_step_id = getattr(plan, "current_step_id", None) or ""
    steps = list(getattr(plan, "steps", []) or [])
    lines = [
        "Current dynamic plan state:",
        f"- Goal: {getattr(plan, 'goal', '')}",
        f"- Status: {getattr(plan, 'status', '')}",
        f"- Current step: {current_step_id or 'none'}",
        (
            "Execution rule: work on the current in_progress step only, use other steps as context, "
            "and call runtime_plan.complete_step with evidence when the current step is satisfied."
        ),
    ]
    counts = _step_status_counts(steps)
    if counts:
        lines.append(f"- Step status counts: {_dict_summary(counts)}")
    for step in steps[:PLAN_EVIDENCE_MAX_STEPS]:
        step_id = getattr(step, "step_id", "")
        marker = " <= current" if current_step_id and step_id == current_step_id else ""
        lines.append(
            "- "
            + f"{step_id}: {getattr(step, 'status', '')}{marker}; "
            + f"{getattr(step, 'title', '')}; {getattr(step, 'objective', '')}"
        )
        is_current = bool(current_step_id and step_id == current_step_id)
        if is_current:
            acceptance = _short_list(getattr(step, "acceptance_criteria", None), limit=3)
            if acceptance:
                lines.append(f"  acceptance: {acceptance}")
            tool_hints = _short_list(getattr(step, "tool_hints", None), limit=6)
            if tool_hints:
                lines.append(f"  tool_hints: {tool_hints}")
        result = getattr(step, "result_summary", None)
        if result:
            lines.append(f"  result: {_truncate_text(result, PLAN_RESULT_SUMMARY_MAX_CHARS)}")
        evidence = _evidence_summary(getattr(step, "evidence", None), limit=4 if is_current else 2)
        if evidence:
            lines.append(f"  evidence: {evidence}")
    if len(steps) > PLAN_EVIDENCE_MAX_STEPS:
        lines.append(f"- Additional steps omitted from prompt context: {len(steps) - PLAN_EVIDENCE_MAX_STEPS}")
    last_execution = getattr(plan, "last_execution", None)
    if isinstance(last_execution, dict):
        last_summary = _last_execution_summary(last_execution)
        if last_summary:
            lines.append(f"- Last execution: {last_summary}")
    return "\n".join(line for line in lines if line.strip())


def _step_status_counts(steps: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for step in steps:
        status = str(getattr(step, "status", "") or "").strip()
        if status:
            counts[status] = counts.get(status, 0) + 1
    return counts


def _dict_summary(value: dict[str, int]) -> str:
    return ", ".join(f"{key}={value[key]}" for key in sorted(value))


def _short_list(value: Any, *, limit: int) -> str:
    if not isinstance(value, list):
        return ""
    items = [_truncate_text(str(item).strip(), PLAN_EVIDENCE_VALUE_MAX_CHARS) for item in value if str(item).strip()]
    if not items:
        return ""
    shown = items[:limit]
    suffix = f"; +{len(items) - limit} more" if len(items) > limit else ""
    return "; ".join(shown) + suffix


def _evidence_summary(value: Any, *, limit: int) -> str:
    if not isinstance(value, list):
        return ""
    items: list[str] = []
    for item in value:
        summary = _evidence_item_summary(item)
        if summary:
            items.append(summary)
    if not items:
        return ""
    shown = items[:limit]
    suffix = f"; +{len(items) - limit} more" if len(items) > limit else ""
    return "; ".join(shown) + suffix


def _evidence_item_summary(item: Any) -> str:
    if not isinstance(item, dict):
        return _truncate_text(str(item).strip(), PLAN_EVIDENCE_VALUE_MAX_CHARS)
    candidates = [
        _path_like_value(item.get("path")),
        _path_like_value(item.get("file_path")),
        _path_like_value(item.get("output_path")),
        _path_like_value(item.get("report_path")),
        _path_like_value(item.get("artifact_path")),
    ]
    output = item.get("output")
    if isinstance(output, dict):
        candidates.extend(
            [
                _path_like_value(output.get("path")),
                _path_like_value(output.get("file_path")),
                _path_like_value(output.get("output_path")),
                _path_like_value(output.get("report_path")),
                _path_like_value(output.get("artifact_path")),
            ]
        )
    message = str(item.get("message") or "").strip()
    candidates.append(message)
    for candidate in candidates:
        if candidate:
            return _truncate_text(candidate, PLAN_EVIDENCE_VALUE_MAX_CHARS)
    return _truncate_text(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str), PLAN_EVIDENCE_VALUE_MAX_CHARS)


def _path_like_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text


def _last_execution_summary(value: dict[str, Any]) -> str:
    parts: list[str] = []
    step_id = str(value.get("step_id") or "").strip()
    status = str(value.get("status") or "").strip()
    result = str(value.get("result_summary") or "").strip()
    if step_id:
        parts.append(f"step_id={step_id}")
    if status:
        parts.append(f"status={status}")
    if result:
        parts.append(f"result={_truncate_text(result, PLAN_RESULT_SUMMARY_MAX_CHARS)}")
    evidence = _evidence_summary(value.get("evidence"), limit=2)
    if evidence:
        parts.append(f"evidence={evidence}")
    return "; ".join(parts)


def _truncate_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 14)].rstrip() + "...[truncated]"


def _message_text(message: BaseMessage) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return str(content)


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


def _matching_node_frame(value: Any, *, node_id: str | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if str(value.get("node_id") or "") != str(node_id or ""):
        return None
    return value


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
