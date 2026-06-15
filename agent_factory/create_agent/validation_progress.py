from __future__ import annotations


def validation_event_from_tool_calls(tool_calls: list[dict[str, object]]) -> str:
    tool_names = {str(call.get("name") or "") for call in tool_calls}
    if "create_agent_control" in tool_names:
        return "control"
    if any(_is_stage_focus_change(call) for call in tool_calls):
        return "focus_change"
    if tool_names & {"write", "edit", "multi_edit"}:
        return "package_change"
    return "none"


def _is_stage_focus_change(tool_call: dict[str, object]) -> bool:
    if str(tool_call.get("name") or "") != "create_agent_stage":
        return False
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return False
    return str(args.get("action") or "") in {"set_focus", "mark_waiting_user"}
