from __future__ import annotations

from typing import Any

from agent_factory.create_agent.control_tool import CREATE_AGENT_WORKSPACE_RESOURCE
from agent_factory.create_agent.runtime_path_repair import apply_runtime_path_repairs, runtime_path_repairs_from_inputs
from agent_factory.create_agent.scaffold import ensure_base_package
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_SCAFFOLD_TOOL_ID = "create_agent_scaffold"


def build_create_agent_scaffold_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_SCAFFOLD_TOOL_ID,
        description=(
            "Materialize or repair the deterministic RuntimeKernel AgentPackage base scaffold. "
            "Use it when validator repair_bundles are machine_applicable, or before semantic package editing."
        ),
        entrypoint="agent_factory.create_agent.scaffold_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["ensure_base_package", "apply_machine_repair"],
                    "description": "Scaffold action to perform.",
                }
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "status": {"type": "string"},
                "created": {"type": "array", "items": {"type": "string"}},
                "updated": {"type": "array", "items": {"type": "string"}},
                "preserved": {"type": "array", "items": {"type": "string"}},
                "manifest_path": {"type": "string"},
                "contract_paths": {"type": "object", "additionalProperties": {"type": "string"}},
                "message": {"type": "string"},
                "applied_bundles": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "action",
                "status",
                "created",
                "updated",
                "preserved",
                "manifest_path",
                "contract_paths",
                "message",
                "applied_bundles",
            ],
            "additionalProperties": False,
        },
        resources={"workspace": CREATE_AGENT_WORKSPACE_RESOURCE},
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.scaffold_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    action = _action(arguments.get("action"))
    workspace = _workspace(resources)
    request_text = workspace.request_path.read_text(encoding="utf-8") if workspace.request_path.exists() else ""
    if action == "ensure_base_package":
        result = {**ensure_base_package(workspace.root, request_text=request_text), "applied_bundles": []}
    else:
        result = _apply_machine_repair(workspace=workspace, request_text=request_text)
    return {
        **result,
        "action": action,
        "message": _message(result),
    }


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    try:
        action = _action(arguments.get("action"))
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=[f"invalid create-agent scaffold request: {type(exc).__name__}: {exc}"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["create-agent scaffold writes only deterministic package base files inside the workspace"],
        facts={"action": action},
    ).model_dump(mode="json")


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _action(value: Any) -> str:
    action = str(value or "").strip()
    if action not in {"ensure_base_package", "apply_machine_repair"}:
        raise ValueError("action must be one of: ensure_base_package, apply_machine_repair")
    return action


def _apply_machine_repair(*, workspace: CreateAgentWorkspace, request_text: str) -> dict[str, Any]:
    report = workspace.read_validation()
    if report is None:
        raise ValueError("apply_machine_repair requires .factory/validation.json with machine-applicable repair bundles")
    created: list[str] = []
    updated: list[str] = []
    preserved: list[str] = []
    applied_bundles: list[str] = []
    for bundle in report.next_action.repair_bundles:
        if not bundle.machine_applicable:
            continue
        if bundle.repair_action in {"materialize_base_package", "materialize_required_contracts"}:
            scaffold_result = ensure_base_package(workspace.root, request_text=request_text)
            created.extend(scaffold_result.get("created") or [])
            updated.extend(scaffold_result.get("updated") or [])
            preserved.extend(scaffold_result.get("preserved") or [])
            applied_bundles.append(bundle.bundle_id)
            continue
        if bundle.repair_action == "normalize_runtime_contract_paths":
            changed = apply_runtime_path_repairs(
                workspace.root,
                runtime_path_repairs_from_inputs(bundle.inputs),
            )
            updated.extend(changed)
            applied_bundles.append(bundle.bundle_id)
            continue
        raise ValueError(f"unsupported machine repair action: {bundle.repair_action}")
    if not applied_bundles:
        raise ValueError("latest validation report does not contain machine-applicable repair bundles")
    return {
        "status": "completed",
        "created": sorted(set(created)),
        "updated": sorted(set(updated)),
        "preserved": sorted(set(preserved)),
        "manifest_path": "agent_package.json",
        "contract_paths": {},
        "applied_bundles": applied_bundles,
    }


def _message(result: dict[str, Any]) -> str:
    changed = len(result.get("created") or []) + len(result.get("updated") or [])
    applied = result.get("applied_bundles") or []
    if applied:
        return f"Machine repair applied; bundles: {', '.join(applied)}; changed files: {changed}."
    return f"Deterministic package scaffold applied; changed files: {changed}."
