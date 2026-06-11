from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from agent_factory.create_agent.workspace import CreateAgentWorkspace


PROMPT_USER_SNIPPET_LIMIT = 6
ACTIVE_HISTORY_MESSAGE_LIMIT = 28
ACTIVE_HISTORY_PRESERVE_MESSAGES = 14
ACTIVE_HISTORY_TOOL_FACT_LIMIT = 12


def project_messages_for_prompt(messages: list[BaseMessage], *, workspace: CreateAgentWorkspace) -> list[BaseMessage]:
    """Project messages for the create-agent supervisor prompt.

    Layer 1: Compact history before the last completed-todo boundary.
    Layer 2: Compact older active-focus history while preserving the recent tool-call boundary.
    No per-message truncation — ToolMessage compression is handled at the gateway layer.
    """
    cutoff = _completed_system_history_cutoff(messages, workspace=workspace)
    prefix: list[BaseMessage] = []
    active_messages = list(messages)
    if cutoff > 0:
        prefix.append(_compacted_history_message(
            messages[:cutoff],
            workspace=workspace,
            reason=(
                "Completed focus history compacted. Completed work is represented by "
                "workspace focus-stage summaries, not by replaying prior chat/tool output."
            ),
        ))
        active_messages = list(messages[cutoff:])
    return [*prefix, *_project_active_focus_history(active_messages, workspace=workspace)]


def _project_active_focus_history(messages: list[BaseMessage], *, workspace: CreateAgentWorkspace) -> list[BaseMessage]:
    if len(messages) <= ACTIVE_HISTORY_MESSAGE_LIMIT:
        return list(messages)
    cutoff = _active_history_cutoff(messages)
    if cutoff <= 0:
        return list(messages)
    compacted = _compacted_history_message(
        messages[:cutoff],
        workspace=workspace,
        reason=(
            "Older active-focus history compacted because the current focus exceeded the prompt projection window. "
            "The recent tool-call/observation boundary is preserved verbatim."
        ),
    )
    return [compacted, *messages[cutoff:]]


def _active_history_cutoff(messages: list[BaseMessage]) -> int:
    cutoff = max(0, len(messages) - ACTIVE_HISTORY_PRESERVE_MESSAGES)
    while cutoff > 0 and isinstance(messages[cutoff], ToolMessage):
        cutoff -= 1
    if cutoff > 0 and _ai_message_has_tool_calls(messages[cutoff - 1]):
        cutoff -= 1
    return cutoff


def _completed_system_history_cutoff(messages: list[BaseMessage], *, workspace: CreateAgentWorkspace) -> int:
    completed_system_ids = {
        item.system_id
        for item in workspace.read_system_state().stages
        if item.status.value == "done"
    }
    if not completed_system_ids:
        return 0
    cutoff = 0
    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage):
            continue
        if str(getattr(message, "name", "") or "") != "create_agent_stage":
            continue
        completion = _system_completion_from_tool_message(message)
        if completion is None:
            continue
        system_id, status = completion
        if system_id in completed_system_ids and status == "done":
            cutoff = index + 1
    while cutoff < len(messages) and isinstance(messages[cutoff], ToolMessage):
        cutoff += 1
    return cutoff


def _system_completion_from_tool_message(message: ToolMessage) -> tuple[str, str] | None:
    try:
        payload = json.loads(str(message.content or ""))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    output = payload.get("output")
    if not isinstance(output, dict):
        return None
    if isinstance(output.get("output"), dict):
        output = output["output"]
    item = output.get("active_focus")
    if not isinstance(item, dict):
        return None
    system_id = str(item.get("system_id") or "").strip()
    status = str(item.get("status") or "").strip()
    if not system_id or not status:
        return None
    return system_id, status


def _compacted_history_message(
    messages: list[BaseMessage],
    *,
    workspace: CreateAgentWorkspace,
    reason: str,
) -> SystemMessage:
    counts: dict[str, int] = {}
    user_snippets: list[str] = []
    tool_names: list[str] = []
    output_refs: list[dict[str, Any]] = []
    tool_facts: list[str] = []
    for message in messages:
        message_type = str(getattr(message, "type", "") or message.__class__.__name__)
        counts[message_type] = counts.get(message_type, 0) + 1
        if isinstance(message, HumanMessage):
            snippet = _message_text_snippet(message, limit=360)
            if snippet:
                user_snippets.append(snippet)
        if isinstance(message, ToolMessage):
            name = str(getattr(message, "name", "") or "")
            if name:
                tool_names.append(name)
            output_refs.extend(_tool_output_refs_from_message(message))
            fact = _tool_observation_fact(message)
            if fact:
                tool_facts.append(fact)
    count_text = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    lines = [
        f"Compacted prior create-agent history. {reason} Full history remains in the LangGraph checkpoint.",
        f"Omitted message counts: {count_text or 'none'}.",
    ]
    unique_tool_names = sorted(set(tool_names))
    if unique_tool_names:
        lines.append("Prior tools observed: " + ", ".join(unique_tool_names[:12]))
    if tool_facts:
        lines.append("Prior tool observations:")
        for fact in tool_facts[-ACTIVE_HISTORY_TOOL_FACT_LIMIT:]:
            lines.append(f"- {fact}")
    if user_snippets:
        lines.append("Prior user inputs:")
        for snippet in user_snippets[-PROMPT_USER_SNIPPET_LIMIT:]:
            lines.append(f"- {snippet}")
    # Preserve resource set paths from workspace (populated by gateway auto-record)
    resource_store = workspace._resource_set_store
    if resource_store is not None and resource_store.size() > 0:
        explored = resource_store.list_paths()
        lines.append(f"Explored resource paths preserved from compacted history ({len(explored)} total):")
        for path in explored[:30]:
            lines.append(f"- {path}")
        if len(explored) > 30:
            lines.append(f"  ... and {len(explored) - 30} more")
    unique_output_refs = _dedupe_output_refs(output_refs)
    if unique_output_refs:
        lines.append("Available output refs preserved from compacted history:")
        for ref in unique_output_refs[:8]:
            lines.append(
                f"- {ref['id']}: tool={ref.get('tool_id') or 'unknown'} | chars={ref.get('size_chars') or 'unknown'}"
            )
    return SystemMessage(content="\n".join(lines))


def _ai_message_has_tool_calls(message: BaseMessage) -> bool:
    if not isinstance(message, AIMessage):
        return False
    return bool(getattr(message, "tool_calls", None) or [])


def _tool_observation_fact(message: ToolMessage) -> str:
    try:
        payload = json.loads(str(message.content or ""))
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    tool_id = str(payload.get("tool_id") or getattr(message, "name", "") or "unknown")
    status = str(payload.get("status") or "")
    text = _compact_observation_text(payload.get("message") or payload.get("output_summary") or "")
    paths = _tool_observation_paths(payload)
    path_text = f" | paths={paths[:4]}" if paths else ""
    output_refs = _dedupe_output_refs(_tool_output_refs_from_message(message))
    ref_text = f" | output_refs={[ref['id'] for ref in output_refs[:3]]}" if output_refs else ""
    return f"{tool_id}: {status or 'observed'}" + (f" | {text}" if text else "") + path_text + ref_text


def _tool_observation_paths(payload: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    _collect_path_values(payload.get("output"), paths)
    _collect_path_values(payload.get("evidence"), paths)
    return _dedupe_texts(paths)


def _collect_path_values(value: Any, paths: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"path", "relative_path"} and isinstance(item, str) and item.strip():
                paths.append(item.strip())
            elif key in {"paths", "changed_files", "target_files"} and isinstance(item, list):
                for child in item:
                    if isinstance(child, str) and child.strip():
                        paths.append(child.strip())
            else:
                _collect_path_values(item, paths)
        return
    if isinstance(value, list):
        for item in value:
            _collect_path_values(item, paths)


def _dedupe_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _compact_observation_text(value: Any, *, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:max(0, limit - 1)]}…"


def _message_text_snippet(message: BaseMessage, *, limit: int) -> str:
    content = message.content
    if isinstance(content, str):
        text = content
    else:
        try:
            text = json.dumps(content, ensure_ascii=False, sort_keys=True)
        except Exception:
            text = str(content)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[:max(0, limit - 1)]}…"


def _tool_output_refs_from_message(message: ToolMessage) -> list[dict[str, Any]]:
    try:
        payload = json.loads(str(message.content or ""))
    except json.JSONDecodeError:
        return []
    refs: list[dict[str, Any]] = []
    _collect_tool_output_refs(payload, refs)
    return refs


def _collect_tool_output_refs(value: Any, refs: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if value.get("type") == "tool_output_ref" and _is_tool_output_id(value.get("id")):
            refs.append(
                {
                    "id": str(value.get("id") or ""),
                    "tool_id": str(value.get("tool_id") or ""),
                    "tool_call_id": str(value.get("tool_call_id") or ""),
                    "created_at": str(value.get("created_at") or ""),
                    "size_chars": value.get("size_chars"),
                }
            )
            return
        compacted = value.get("_tool_output_compacted")
        if isinstance(compacted, dict):
            output_ref = compacted.get("output_ref")
            if isinstance(output_ref, dict):
                _collect_tool_output_refs(output_ref, refs)
        for item in value.values():
            _collect_tool_output_refs(item, refs)
        return
    if isinstance(value, list):
        for item in value:
            _collect_tool_output_refs(item, refs)


def _dedupe_output_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for ref in refs:
        output_id = str(ref.get("id") or "").strip()
        if not _is_tool_output_id(output_id) or output_id in seen:
            continue
        seen.add(output_id)
        result.append(ref)
    return result


def _is_tool_output_id(value: Any) -> bool:
    text = str(value or "")
    return len(text) == len("toolout_") + 32 and text.startswith("toolout_")
