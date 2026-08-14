from __future__ import annotations

from typing import Any

from combo.runtime_protocol import RuntimeExecutionIdentity
from combo.tooling.builtins.skillhub.specs import (
    RUNTIME_IDENTITY_RESOURCE,
    SKILLHUB_RUNTIME_RESOURCE,
)
from combo.tooling.envelope import tool_envelope
from combo.tooling.skillhub.search_query import normalize_skillhub_search_query
from combo.tooling.skillhub.service import SkillHubService


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action in {"status", "search"}:
        return {"action": "allow", "risk_level": "low", "reasons": ["read-only SkillHub operation"]}
    if action in {"install", "remove"}:
        return {"action": "ask", "risk_level": "high", "reasons": [f"SkillHub {action} changes the unified Skill pool"]}
    return {"action": "deny", "risk_level": "high", "reasons": ["unsupported SkillHub action"]}


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    service = resources.get(SKILLHUB_RUNTIME_RESOURCE)
    identity = resources.get(RUNTIME_IDENTITY_RESOURCE)
    if not isinstance(service, SkillHubService):
        raise RuntimeError("SkillHub runtime is not configured")
    if not isinstance(identity, RuntimeExecutionIdentity) or identity.runtime_role != "main":
        raise PermissionError("SkillHub is available only to the main Agent")
    action = str(arguments.get("action") or "").strip()
    if action == "status":
        output = service.status()
    elif action == "search":
        output = service.search(normalize_skillhub_search_query(str(arguments.get("query") or "")))
    elif action == "install":
        output = service.install(str(arguments.get("skill") or ""))
    elif action == "remove":
        output = service.remove(str(arguments.get("skill") or ""))
    else:
        raise ValueError(f"unsupported SkillHub action: {action}")
    return tool_envelope(output, summary=str(output.get("message") or f"SkillHub {action} completed"))
