from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from agent_factory.tooling.execution_context import tool_approval_override


def tool_approval_resume_context(resume_payload: Any):
    if _is_approved_tool_resume_payload(resume_payload):
        return tool_approval_override(reason="approved agent package tool approval resume")
    return nullcontext()


def _is_approved_tool_resume_payload(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if _is_approved_tool_decision(value):
        return True
    if value and all(isinstance(item, dict) for item in value.values()):
        return any(_is_approved_tool_decision(item) for item in value.values())
    return False


def _is_approved_tool_decision(value: dict[str, Any]) -> bool:
    action = str(value.get("action") or value.get("choice") or "").strip().lower()
    if action in {"approve", "approved", "trust", "trust_tool", "always_allow", "no_approval", "无需审批"}:
        return True
    approved = value.get("approved", value.get("approve"))
    return approved is True or (isinstance(approved, str) and approved.strip().lower() in {"true", "yes", "y"})
