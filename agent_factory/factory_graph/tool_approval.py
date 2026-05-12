from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage
from langgraph.types import interrupt


FACTORY_TOOL_APPROVAL_NODE = "tool_approval"


def approve_tool_calls(state: dict[str, Any]) -> dict[str, Any]:
    """Interrupt before executing protected tool calls."""

    requests = _approval_requests(
        messages=state.get("messages", []),
        protected_tool_ids=set(state.get("protected_tool_ids", [])),
    )
    if not requests:
        return {"tool_approval": {"required": False, "approved": True}}

    decision = interrupt(
        {
            "type": "tool_approval",
            "message": "检测到需要人工确认的工具调用，请确认执行、拒绝，或输入审查意见让模型重写工具调用。",
            "choices": {"approve": "-y", "deny": "-n", "revise": "custom"},
            "requests": requests,
        }
    )
    action = _decision_action(decision)
    if action == "approve":
        return {"tool_approval": {"required": True, "approved": True, "action": action, "requests": requests}}

    if action == "revise":
        guidance = _revision_guidance(decision)
        return {
            "tool_approval": {
                "required": True,
                "approved": False,
                "action": action,
                "revision_guidance": guidance,
                "requests": requests,
            },
            "messages": [
                ToolMessage(
                    content=(
                        "用户没有批准执行该工具调用，并给出了重新生成工具调用的审查意见："
                        f"{guidance}"
                    ),
                    name=request["tool_name"],
                    tool_call_id=request["tool_call_id"],
                )
                for request in requests
            ],
        }

    return {
        "tool_approval": {"required": True, "approved": False, "action": action, "requests": requests},
        "messages": [
            ToolMessage(
                content="用户拒绝执行该工具调用。",
                name=request["tool_name"],
                tool_call_id=request["tool_call_id"],
            )
            for request in requests
        ],
    }


def route_after_tool_approval(state: dict[str, Any], *, approved: str, denied: str) -> str:
    tool_approval = state.get("tool_approval") or {}
    if tool_approval.get("approved") is False:
        return denied
    return approved


def _approval_requests(
    *,
    messages: list[BaseMessage],
    protected_tool_ids: set[str],
) -> list[dict[str, Any]]:
    if not messages:
        return []
    tool_calls = getattr(messages[-1], "tool_calls", None) or []
    requests: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        tool_name = str(tool_call.get("name") or "")
        if tool_name not in protected_tool_ids:
            continue
        args = tool_call.get("args") or {}
        requests.append(
            {
                "tool_call_id": str(tool_call.get("id") or ""),
                "tool_name": tool_name,
                "args": args,
                "summary": _tool_call_summary(tool_name, args),
            }
        )
    return requests


def _tool_call_summary(tool_name: str, args: dict[str, Any]) -> str:
    command = args.get("command")
    if command:
        return str(command)
    process_id = args.get("process_id")
    if process_id:
        return f"process_id={process_id}"
    return tool_name


def _is_approved(decision: Any) -> bool:
    if isinstance(decision, bool):
        return decision
    if isinstance(decision, str):
        return decision.strip().lower() in {"-y", "y", "yes", "true", "approve", "approved"}
    if isinstance(decision, dict):
        value = decision.get("approved", decision.get("approve", decision.get("choice")))
        return _is_approved(value)
    return False


def _decision_action(decision: Any) -> str:
    if _is_approved(decision):
        return "approve"
    if isinstance(decision, str):
        normalized = decision.strip().lower()
        if normalized in {"revise", "retry", "custom", "edit", "rewrite"}:
            return "revise"
        return "deny"
    if isinstance(decision, dict):
        action = str(decision.get("action") or decision.get("choice") or "").strip().lower()
        if action in {"approve", "approved"}:
            return "approve"
        if action in {"revise", "retry", "custom", "edit", "rewrite"}:
            return "revise"
    return "deny"


def _revision_guidance(decision: Any) -> str:
    if isinstance(decision, str):
        return decision.strip()
    if isinstance(decision, dict):
        for key in ("revision_guidance", "guidance", "input_text", "message"):
            value = decision.get(key)
            if value:
                return str(value).strip()
    return "请根据用户审查意见重新生成更合适的工具调用。"
