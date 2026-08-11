from __future__ import annotations

from typing import Any

from agent_factory.dynamic_runtime.control_plane_store import WorkspaceSchedulerStore
from agent_factory.runtime_protocol import RuntimeExecutionIdentity
from agent_factory.tooling.builtins.scheduler.specs import (
    RUNTIME_IDENTITY_RESOURCE,
    SCHEDULER_RUNTIME_RESOURCE,
)
from agent_factory.tooling.envelope import tool_envelope


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action in {"list", "describe"}:
        return {"action": "allow", "risk_level": "low", "reasons": ["read-only scheduler operation"]}
    if action in {"create", "pause", "resume"}:
        return {"action": "ask", "risk_level": "medium", "reasons": ["changes a workspace scheduled task"]}
    if action == "delete":
        return {"action": "ask", "risk_level": "high", "reasons": ["deletes a workspace scheduled task"]}
    return {"action": "deny", "risk_level": "high", "reasons": ["unsupported scheduler action"]}


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    store = resources.get(SCHEDULER_RUNTIME_RESOURCE)
    identity = resources.get(RUNTIME_IDENTITY_RESOURCE)
    if not isinstance(store, WorkspaceSchedulerStore):
        raise RuntimeError("scheduler runtime is not configured")
    identity = _require_main(identity)
    action = str(arguments.get("action") or "").strip()
    if action == "list":
        output = {"action": action, "jobs": store.jobs((identity.workspace_id,))}
    elif action == "describe":
        output = {"action": action, "job": _owned_job(store, identity, arguments)}
    elif action == "create":
        output = {
            "action": action,
            "job": store.create_job({
                "workspace_id": identity.workspace_id,
                "task_content": _required_text(arguments, "task_content"),
                "schedule_type": _required_text(arguments, "schedule_type"),
                "schedule_expr": _required_text(arguments, "schedule_expr"),
                "timezone": _required_text(arguments, "timezone"),
                "strategy": str(arguments.get("strategy") or "auto"),
                "approval_policy": str(arguments.get("approval_policy") or "ask"),
            }),
        }
    elif action in {"pause", "resume", "delete"}:
        job = _owned_job(store, identity, arguments)
        status = {"pause": "paused", "resume": "enabled", "delete": "deleted"}[action]
        store.set_status(str(job["job_id"]), status)
        output = {"action": action, "job_id": str(job["job_id"]), "status": status}
    else:
        raise ValueError(f"unsupported scheduler action: {action}")
    return tool_envelope(output, summary=f"scheduler {action} completed")


def _owned_job(
    store: WorkspaceSchedulerStore,
    identity: RuntimeExecutionIdentity,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    job = store.require_job(_required_text(arguments, "job_id"))
    if str(job.get("workspace_id") or "") != identity.workspace_id:
        raise PermissionError("scheduled task belongs to a different workspace")
    return job


def _require_main(identity: Any) -> RuntimeExecutionIdentity:
    if not isinstance(identity, RuntimeExecutionIdentity) or identity.runtime_role != "main":
        raise PermissionError("scheduler management is available only to the main Agent")
    return identity


def _required_text(arguments: dict[str, Any], name: str) -> str:
    value = str(arguments.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value
