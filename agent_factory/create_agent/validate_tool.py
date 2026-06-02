from __future__ import annotations

from typing import Any

from agent_factory.create_agent.control_tool import CREATE_AGENT_WORKSPACE_RESOURCE
from agent_factory.create_agent.validator import CreateAgentPackageValidator
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_VALIDATE_TOOL_ID = "create_agent_validate"
VALIDATION_SCOPES = [
    "workspace_hygiene",
    "package_shape",
    "runtime_contract_build",
    "assembly_compile",
    "python_syntax",
    "full_static",
]


def build_create_agent_validate_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_VALIDATE_TOOL_ID,
        description=(
            "Run the create-agent package validator through a controlled entrypoint. "
            "Use this instead of shell commands when you need validation feedback."
        ),
        entrypoint="agent_factory.create_agent.validate_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": VALIDATION_SCOPES,
                    "default": "full_static",
                    "description": "Validation scope to run.",
                },
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Optional package-relative files that changed.",
                },
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "report_digest": {"type": "object", "additionalProperties": True},
                "report_path": {"type": "string"},
            },
            "required": ["report_digest", "report_path"],
            "additionalProperties": False,
        },
        resources={"workspace": CREATE_AGENT_WORKSPACE_RESOURCE},
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.validate_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    scope = _scope(arguments.get("scope"))
    changed_files = _changed_files(arguments.get("changed_files"))
    report = CreateAgentPackageValidator().validate(
        workspace.root,
        scope=scope,
        changed_files=changed_files,
    )
    workspace.write_validation(report)
    return {
        "report_digest": report.to_digest().model_dump(mode="json"),
        "report_path": str(workspace.validation_path),
    }


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    try:
        scope = _scope(arguments.get("scope"))
        _changed_files(arguments.get("changed_files"))
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=[f"invalid create-agent validation request: {type(exc).__name__}: {exc}"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["create-agent validation is read-only within the package workspace"],
        facts={"scope": scope},
    ).model_dump(mode="json")


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _scope(value: Any) -> str:
    scope = str(value or "full_static").strip()
    if scope not in VALIDATION_SCOPES:
        raise ValueError(f"scope must be one of: {', '.join(VALIDATION_SCOPES)}")
    return scope


def _changed_files(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError("changed_files must be a list of non-empty package-relative paths")
    return [item.strip() for item in value]
