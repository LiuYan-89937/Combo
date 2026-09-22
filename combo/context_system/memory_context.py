from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from pydantic import ValidationError

from combo.context_system.schema import ContextCandidate, ContextQuery, CrossSessionMemoryPolicy, MemoryContextSnapshot
from combo.context_system.token_estimation import message_text


MEMORY_CONTEXT_KEY = "memory_context"
MEMORY_CONTEXT_VERSION = "memory_context.v1"


def query_components(state: Any) -> dict[str, str]:
    parts = {}
    current = str(state.conversation.current_user_input or "").strip()
    if current:
        parts["current_request"] = current
    plan = state.plan
    if plan.status == "active":
        if plan.goal.strip():
            parts["task_goal"] = plan.goal.strip()
        step = next((step for step in plan.steps if step.step_id == plan.current_step_id), None)
        if step is not None and step.status in {"pending", "in_progress"}:
            parts["current_task"] = step.objective.strip() or step.title.strip()
    return parts


def context_key(state: Any) -> str:
    return _digest({
        "run_id": state.run.run_id, "runtime_instance_id": state.run.runtime_instance_id,
        "session_id": state.run.session_id, "workspace_id": state.run.workspace_id,
        "input_id": state.conversation.current_user_input_id, "query": query_components(state),
    })


def memory_query(state: Any, *, node_id: str, policy: CrossSessionMemoryPolicy) -> ContextQuery:
    components = query_components(state)
    return ContextQuery(
        node_id=node_id, components=components,
        limit=policy.max_candidates, min_relevance=policy.min_relevance,
    )


def read_memory_snapshot(state: Any, *, node_id: str | None = None) -> MemoryContextSnapshot | None:
    raw = state.context.model_context.get(MEMORY_CONTEXT_KEY)
    if not isinstance(raw, dict) or raw.get("version") != MEMORY_CONTEXT_VERSION:
        return None
    try:
        snapshot = MemoryContextSnapshot.model_validate(raw)
    except ValidationError:
        return None
    if snapshot.context_key != context_key(state):
        return None
    if node_id is not None and snapshot.node_id != node_id:
        return None
    return snapshot


def replace_memory_snapshot(state: Any, snapshot: MemoryContextSnapshot | None) -> None:
    # Retire the old checkpoint representation once, without retaining its
    # duplicate per-node frames as fallback inputs.
    model_context = {
        key: value for key, value in state.context.model_context.items()
        if key not in {MEMORY_CONTEXT_KEY, "runtime_turn_evidence", "llm_context_frame"}
        and not (isinstance(value, dict) and value.get("version") == "llm_context_frame.v0")
    }
    if snapshot is not None:
        model_context[MEMORY_CONTEXT_KEY] = snapshot.model_dump(mode="json")
    state.context.model_context = model_context


def memory_tool_payload(message: Any) -> dict | None:
    if not isinstance(message, ToolMessage) or message.name != "memory" or message.status != "success":
        return None
    try:
        payload = json.loads(message_text(message))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("status") != "completed":
        return None
    output = payload.get("output")
    context = output.get(MEMORY_CONTEXT_KEY) if isinstance(output, dict) else None
    if (not isinstance(context, dict) or context.get("version") != MEMORY_CONTEXT_VERSION
            or output.get("action") != "search"):
        return None
    return payload


def explicit_memory_candidates(messages: list[Any], state: Any) -> list[ContextCandidate]:
    boundary = None
    input_id = state.conversation.current_user_input_id
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if not isinstance(message, HumanMessage):
            continue
        if (input_id and message.id == input_id) or (not input_id and message_text(message) == state.conversation.current_user_input):
            boundary = index
            break
    if boundary is None:
        return []
    items = []
    for message in reversed(messages[boundary + 1:]):
        payload = memory_tool_payload(message)
        if payload is None:
            continue
        context = payload["output"][MEMORY_CONTEXT_KEY]
        if context.get("runtime_instance_id") != state.run.runtime_instance_id:
            continue
        for raw in context.get("items", []):
            try:
                item = ContextCandidate.model_validate(raw)
            except ValidationError:
                continue
            item.metadata["retrieval_origin"] = "explicit"
            items.append(item)
    return items


def project_memory_tool_messages(messages: list[Any], *, selected_ids: set[str]) -> list[Any]:
    projected = []
    for message in messages:
        payload = memory_tool_payload(message)
        if payload is None:
            projected.append(message)
            continue
        context = payload["output"][MEMORY_CONTEXT_KEY]
        refs = []
        for item in context.get("items", []):
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") or {}
            refs.append({
                "memory_id": metadata.get("memory_id"), "revision": metadata.get("revision"),
                "in_current_memory_context": item.get("candidate_id") in selected_ids,
            })
        payload["output"][MEMORY_CONTEXT_KEY] = {
            "version": MEMORY_CONTEXT_VERSION, "references": refs,
            "content_location": "current_request_supplementary_memory_data",
        }
        projected.append(message.model_copy(update={"content": json.dumps(payload, ensure_ascii=False)}))
    return projected


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
