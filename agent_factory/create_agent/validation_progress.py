from __future__ import annotations


def validation_event_from_tool_calls(tool_calls: list[dict[str, object]]) -> str:
    tool_names = {str(call.get("name") or "") for call in tool_calls}
    if "create_agent_control" in tool_names:
        return "control"
    if tool_names & {"write", "edit", "multi_edit"}:
        return "package_change"
    return "none"
