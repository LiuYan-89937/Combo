from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.collaboration_system.parent_controller import (
    create_parent_controlled_session,
    parent_agent_context,
    require_parent_owned_session,
)
from agent_factory.collaboration_system.store import CollaborationStore, resolve_collaboration_store_path
from agent_factory.factory_graph.frontend_bridge.agent_package_repository import AgentPackageRepository
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    store = CollaborationStore(_store_path(resources))
    if action == "start":
        output = _start(arguments, resources, store)
    elif action == "respond":
        output = _respond(arguments, resources, store)
    elif action == "cancel":
        output = _cancel(arguments, resources, store)
    else:
        raise ValueError(f"unsupported agent_evolve action: {action}")
    return tool_envelope(output, summary=str(output.get("message") or ""))


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action in {"start", "respond", "cancel"}:
        return ToolRiskResult(
            action="inherit",
            risk_level="medium",
            reasons=["Agent evolution mutates a published package or its active evolution state"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="deny", risk_level="medium", reasons=[f"unsupported action: {action}"]
    ).model_dump(mode="json")


def _start(arguments: dict[str, Any], resources: dict[str, Any], store: CollaborationStore) -> dict[str, Any]:
    parent = parent_agent_context(resources, tool_id="agent_evolve")
    package_id = _required_text(arguments, "package_id")
    if package_id == parent.package_id:
        raise ValueError("agent_evolve cannot evolve the currently running parent Agent")
    repository = AgentPackageRepository.from_paths()
    manifest_path = repository.manifest_path(package_id)
    repository.load_manifest(manifest_path)
    if repository.package_origin(manifest_path) != "user":
        raise ValueError("built-in Agent packages cannot be evolved")
    goal = _required_text(arguments, "goal")
    session, _ = create_parent_controlled_session(
        store,
        resources,
        title=f"进化 Agent：{package_id}",
        tool_id="agent_evolve",
        task_kind="evolve",
        context=parent,
    )
    evolution_id = str(session["collaboration_id"])
    request = store.create_evolution_request(
        evolution_id,
        {
            "package_id": package_id,
            "goal": _evolution_goal(goal, _string_list(arguments.get("constraints"))),
            "constraints": _string_list(arguments.get("constraints")),
            "runtime_user_config": _runtime_user_config(resources),
        },
    )
    return {
        "action": "start",
        "status": request["status"],
        "evolution_id": evolution_id,
        "background_task_id": evolution_id,
        "request_id": request["request_id"],
        "package_id": package_id,
        "message": f"{package_id} 的进化已异步启动；状态变化会自动回到当前会话。",
    }


def _respond(arguments: dict[str, Any], resources: dict[str, Any], store: CollaborationStore) -> dict[str, Any]:
    evolution_id = _required_text(arguments, "evolution_id")
    require_parent_owned_session(store, resources, evolution_id, tool_id="agent_evolve")
    request_id = _required_text(arguments, "request_id")
    request = store.get_evolution_request(evolution_id, request_id)
    if str(request.get("status") or "") != "blocked":
        raise ValueError("agent_evolve respond requires a blocked evolution request")
    result_payload = request.get("result_payload") if isinstance(request.get("result_payload"), dict) else {}
    pending = result_payload.get("pending_interrupt") if isinstance(result_payload.get("pending_interrupt"), dict) else {}
    resume_payload = _resume_payload(arguments, pending)
    updated = store.update_evolution_request(
        evolution_id,
        request_id,
        {
            "status": "resume_requested",
            "message": "已收到进化补充信息，宿主将恢复原进化运行。",
            "result_payload": {
                **result_payload,
                "resume_payload": resume_payload,
                "runtime_status": "resume_requested",
            },
        },
    )
    return {
        "action": "respond",
        "status": updated.get("status"),
        "evolution_id": evolution_id,
        "request_id": request_id,
        "message": "补充信息已进入原进化运行，不会新开一轮。",
    }


def _cancel(arguments: dict[str, Any], resources: dict[str, Any], store: CollaborationStore) -> dict[str, Any]:
    evolution_id = _required_text(arguments, "evolution_id")
    require_parent_owned_session(store, resources, evolution_id, tool_id="agent_evolve")
    request_id = _required_text(arguments, "request_id")
    request = store.get_evolution_request(evolution_id, request_id)
    if str(request.get("status") or "") in {"completed", "failed", "cancelled"}:
        return {
            "action": "cancel",
            "status": "unchanged",
            "evolution_id": evolution_id,
            "request_id": request_id,
            "message": "该进化请求已经结束。",
        }
    reason = str(arguments.get("reason") or "主 Agent 取消了进化请求。").strip()
    result_payload = request.get("result_payload") if isinstance(request.get("result_payload"), dict) else {}
    store.update_evolution_request(
        evolution_id,
        request_id,
        {
            "status": "cancelled",
            "message": reason,
            "result_payload": {
                **result_payload,
                "runtime_status": "cancelled",
                "cancellation_requested": True,
            },
        },
    )
    return {
        "action": "cancel",
        "status": "cancelled",
        "evolution_id": evolution_id,
        "request_id": request_id,
        "message": f"{reason} 宿主正在停止并回滚未完成的进化。",
    }


def _resume_payload(arguments: dict[str, Any], pending: dict[str, Any]) -> dict[str, Any]:
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
    is_tool_approval = (
        bool(requests)
        or str(payload.get("type") or "") == "tool_approval"
        or str(pending.get("event_type") or "") == "tool_approval_requested"
    )
    response = str(arguments.get("response") or "").strip()
    if not is_tool_approval:
        if not response:
            raise ValueError("response is required for an evolution question")
        return {
            "action": "answer",
            "input_text": response,
            "answer": response,
            "message": response,
        }
    decision = str(arguments.get("decision") or "").strip()
    if decision not in {"approve", "deny", "revise"}:
        raise ValueError("decision is required for an evolution tool approval")
    first = next((item for item in requests if isinstance(item, dict)), payload)
    return {
        "type": "tool_approval",
        "interrupt_event_id": pending.get("event_id"),
        "pending_request_id": pending.get("request_id"),
        "original_request_id": pending.get("request_id"),
        "action": decision,
        "approved": decision == "approve",
        "tool_call_id": first.get("tool_call_id"),
        "tool_call_ids": [
            str(item.get("tool_call_id") or "")
            for item in requests
            if isinstance(item, dict) and str(item.get("tool_call_id") or "")
        ],
        "requests": requests,
        "approval": {
            "decision": decision,
            "approved_by": "parent_agent",
            "reason": response,
        },
        **({"revision_guidance": response} if decision == "revise" and response else {}),
    }


def _runtime_user_config(resources: dict[str, Any]) -> dict[str, Any]:
    execution = resources.get("runtime_execution_config")
    user_config = execution.get("user_config") if isinstance(execution, dict) else None
    if not isinstance(user_config, dict):
        return {}
    allowed = ("model_profile_overrides", "reasoning_intensity")
    return {key: user_config[key] for key in allowed if key in user_config}


def _evolution_goal(goal: str, constraints: list[str]) -> str:
    if not constraints:
        return goal
    return goal + "\n\n必须遵守的进化约束：\n" + "\n".join(f"- {item}" for item in constraints)


def _store_path(resources: dict[str, Any]) -> Path:
    root = Path(_required_text(resources, "collaboration_root")).expanduser()
    return resolve_collaboration_store_path(root / "factory.sqlite")


def _required_text(values: dict[str, Any], key: str) -> str:
    text = str(values.get(key) or "").strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(text for item in value if (text := str(item or "").strip())))
