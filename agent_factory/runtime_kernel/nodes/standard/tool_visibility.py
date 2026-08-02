from __future__ import annotations

from typing import Any

from agent_factory.collaboration_runtime_policy import (
    COLLABORATION_CONTEXT_TOOL_IDS,
    COLLABORATION_EXCLUDED_TOOL_IDS,
    DELEGATED_RESULT_TOOL_ID,
)
from agent_factory.runtime_kernel.plan_execute_tools import merge_tool_ids
from agent_factory.runtime_kernel.state import RuntimeState


def runtime_excluded_tool_ids(state: RuntimeState) -> list[str]:
    user_config = state.runtime_config.user_config
    contextual_exclusions = [] if _delegation_context_enabled(user_config) else [DELEGATED_RESULT_TOOL_ID]
    if not isinstance(user_config, dict) or not _collaboration_context_enabled(user_config):
        return contextual_exclusions
    access = user_config.get("runtime_tool_access")
    ids = access.get("excluded_tool_ids") if isinstance(access, dict) else []
    configured = ids if isinstance(ids, list) else []
    return merge_tool_ids([
        *contextual_exclusions,
        *sorted(COLLABORATION_EXCLUDED_TOOL_IDS),
        *[
            tool_id
            for item in configured
            if (tool_id := str(item or "").strip()) in COLLABORATION_EXCLUDED_TOOL_IDS
        ],
    ])


def runtime_extra_allowed_tool_ids(state: RuntimeState) -> list[str]:
    user_config = state.runtime_config.user_config
    if not isinstance(user_config, dict):
        return []
    access = user_config.get("runtime_tool_access")
    if not isinstance(access, dict):
        return []
    ids = access.get("extra_allowed_tool_ids")
    if not isinstance(ids, list):
        return []
    allowed: list[str] = []
    for item in ids:
        tool_id = str(item or "").strip()
        if tool_id in COLLABORATION_CONTEXT_TOOL_IDS and _collaboration_context_enabled(user_config):
            allowed.append(tool_id)
        elif tool_id == DELEGATED_RESULT_TOOL_ID and _delegation_context_enabled(user_config):
            allowed.append(tool_id)
    return merge_tool_ids(allowed)


def _collaboration_context_enabled(user_config: dict[str, Any]) -> bool:
    value = str(user_config.get("collaboration_id") or "").strip()
    return bool(value)


def _delegation_context_enabled(user_config: Any) -> bool:
    if not isinstance(user_config, dict):
        return False
    context = user_config.get("delegation_context")
    if not isinstance(context, dict):
        return False
    return bool(
        str(context.get("collaboration_id") or "").strip()
        and str(context.get("task_id") or "").strip()
    )
