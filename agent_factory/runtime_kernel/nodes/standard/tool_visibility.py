from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.plan_execute_tools import merge_tool_ids
from agent_factory.runtime_kernel.state import RuntimeState


COLLABORATION_CONTEXT_TOOL_IDS = frozenset({"collaboration", "agent_list", "agent_search", "agent_manufacture"})
COLLABORATION_EXCLUDED_TOOL_IDS = frozenset({"skillhub"})


def runtime_excluded_tool_ids(state: RuntimeState) -> list[str]:
    user_config = state.runtime_config.user_config
    if not isinstance(user_config, dict) or not _collaboration_context_enabled(user_config):
        return []
    access = user_config.get("runtime_tool_access")
    if not isinstance(access, dict):
        return []
    ids = access.get("excluded_tool_ids")
    if not isinstance(ids, list):
        return []
    return merge_tool_ids([
        tool_id
        for item in ids
        if (tool_id := str(item or "").strip()) in COLLABORATION_EXCLUDED_TOOL_IDS
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
    return merge_tool_ids(allowed)


def _collaboration_context_enabled(user_config: dict[str, Any]) -> bool:
    value = str(user_config.get("collaboration_id") or "").strip()
    return bool(value)
