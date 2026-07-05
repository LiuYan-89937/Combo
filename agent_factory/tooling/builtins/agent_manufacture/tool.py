from __future__ import annotations

import os
from typing import Any

from agent_factory.collaboration_system.store import CollaborationStore, resolve_collaboration_store_path
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


COLLABORATION_ROOT_ENV = "AGENTFACTORY_COLLABORATION_ROOT"


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    store = CollaborationStore(_store_path(resources))
    collaboration_id = _required_text(arguments, "collaboration_id")
    request = store.create_manufacturing_request(collaboration_id, _request_payload(arguments))
    output = {
        "status": request["status"],
        "request_id": request["request_id"],
        "collaboration_id": collaboration_id,
        "create_agent_session_id": request.get("create_agent_session_id"),
        "message": "制造请求已登记，宿主协作服务会自动执行制造并在通过验证后发布。",
        "next_step": "等待 manufacturing_completed 协作消息；发布完成后再次调用 agent_search 获取新 package_id。",
    }
    return tool_envelope(output, summary=output["message"])


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    collaboration_id = str(arguments.get("collaboration_id") or "").strip()
    if not collaboration_id:
        return ToolRiskResult(
            action="deny",
            risk_level="medium",
            reasons=["agent_manufacture requires collaboration_id"],
        ).model_dump(mode="json")
    missing = [
        key
        for key in (
            "agent_name",
            "purpose",
            "delivery_standards",
            "reason_existing_agents_insufficient",
        )
        if _is_empty(arguments.get(key))
    ]
    if missing:
        return ToolRiskResult(
            action="deny",
            risk_level="medium",
            reasons=["missing required manufacturing fields: " + ", ".join(missing)],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="inherit",
        risk_level="medium",
        reasons=["agent manufacturing creates and publishes a new package in collaboration delegated mode"],
    ).model_dump(mode="json")


def _request_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_name": _required_text(arguments, "agent_name"),
        "purpose": _required_text(arguments, "purpose"),
        "target_tasks": _string_list(arguments.get("target_tasks")),
        "delivery_standards": _string_list(arguments.get("delivery_standards")),
        "reason_existing_agents_insufficient": _required_text(arguments, "reason_existing_agents_insufficient"),
        "preferred_pattern": _optional_text(arguments.get("preferred_pattern")),
        "constraints": _string_list(arguments.get("constraints")),
        "source_agent_search": arguments.get("source_agent_search") if isinstance(arguments.get("source_agent_search"), dict) else {},
    }


def _store_path(resources: dict[str, Any]) -> str | None:
    root = str(resources.get("collaboration_root") or os.getenv(COLLABORATION_ROOT_ENV) or "").strip()
    if not root:
        return None
    return str(resolve_collaboration_store_path(os.path.join(root, "factory.sqlite")))


def _required_text(arguments: dict[str, Any], key: str) -> str:
    value = _optional_text(arguments.get(key))
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _optional_text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _is_empty(value: Any) -> bool:
    if isinstance(value, list):
        return not _string_list(value)
    return not str(value or "").strip()
