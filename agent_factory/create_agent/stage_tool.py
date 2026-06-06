from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_factory.create_agent.control_tool import CREATE_AGENT_WORKSPACE_RESOURCE
from agent_factory.create_agent.models import SystemManufacturingState, SystemStageStatus
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_STAGE_TOOL_ID = "create_agent_stage"


def build_create_agent_stage_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_STAGE_TOOL_ID,
        description=(
            "Inspect and update the active create-agent RuntimeKernel system manufacturing stage. "
            "Use this instead of editing .factory/system_state.json directly."
        ),
        entrypoint="agent_factory.create_agent.stage_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "start", "repair", "block_user"],
                },
                "system_id": {"type": "string"},
                "summary": {"type": "string"},
                "issue": {"type": "object", "additionalProperties": True},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "message": {"type": "string"},
                "state": {"type": "object", "additionalProperties": True},
                "active_system": {"type": ["object", "null"], "additionalProperties": True},
            },
            "required": ["action", "message", "state", "active_system"],
            "additionalProperties": False,
        },
        resources={"workspace": CREATE_AGENT_WORKSPACE_RESOURCE},
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.stage_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    state = workspace.read_system_state()
    action = str(arguments.get("action") or "").strip()
    if action == "list":
        return _output(action=action, message="Current RuntimeKernel system manufacturing state.", state=state)
    if action == "start":
        stage = _target_stage(state, arguments)
        if stage.status == SystemStageStatus.done:
            raise ValueError(f"system already done: {stage.system_id}")
        state = state.update_stage(stage.model_copy(update={"status": SystemStageStatus.in_progress}))
        workspace.write_system_state(state)
        return _output(action=action, message=f"System started: {stage.system_id}", state=state)
    if action == "repair":
        stage = _target_stage(state, arguments)
        state = state.update_stage(stage.model_copy(update={"status": SystemStageStatus.failed_needs_repair}))
        workspace.write_system_state(state)
        return _output(action=action, message=f"System needs repair: {stage.system_id}", state=state)
    if action == "block_user":
        stage = _target_stage(state, arguments)
        state = state.update_stage(stage.model_copy(update={"status": SystemStageStatus.blocked_waiting_user}))
        workspace.write_system_state(state)
        return _output(action=action, message=f"System blocked waiting for user: {stage.system_id}", state=state)
    raise ValueError("action must be one of: list, start, repair, block_user")


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action not in {"list", "start", "repair", "block_user"}:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=["invalid create-agent stage action"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["create-agent stage action is schema-validated"],
        facts={"action": action},
    ).model_dump(mode="json")


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _target_stage(state: SystemManufacturingState, arguments: dict[str, Any]):
    system_id = str(arguments.get("system_id") or state.active_system_id or "").strip()
    if not system_id:
        stage = state.active_stage()
        if stage is None:
            raise ValueError("no active system")
        return stage
    for stage in state.stages:
        if stage.system_id == system_id:
            return stage
    raise KeyError(f"unknown system_id: {system_id}")


def _output(*, action: str, message: str, state: SystemManufacturingState) -> dict[str, Any]:
    active = state.active_stage()
    return {
        "action": action,
        "message": message,
        "state": state.working_set(),
        "active_system": active.to_digest() if active else None,
        "updated_at": datetime.now(UTC).isoformat(),
    }
