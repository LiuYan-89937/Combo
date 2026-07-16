from __future__ import annotations


COLLABORATION_CONTEXT_TOOL_IDS = frozenset({"collaboration", "agent_list", "agent_search", "agent_manufacture"})
COLLABORATION_EXCLUDED_TOOL_IDS = frozenset({"skillhub", "bash", "bash_status", "bash_stop"})


def collaboration_runtime_tool_access() -> dict[str, list[str]]:
    return {
        "extra_allowed_tool_ids": sorted(COLLABORATION_CONTEXT_TOOL_IDS),
        "excluded_tool_ids": sorted(COLLABORATION_EXCLUDED_TOOL_IDS),
    }
