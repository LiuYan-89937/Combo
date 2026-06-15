from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from agent_factory.create_agent.models import PackageToolProbeRecord
from agent_factory.create_agent.validation_gate import _package_fingerprint
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE, ToolOutputStore
from agent_factory.tooling.providers import PackageToolProvider, ToolProviderContext
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_PROBE_TOOL_ID = "create_agent_probe_tool"


def build_create_agent_probe_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_PROBE_TOOL_ID,
        description=(
            "Inspect and probe package-owned tools generated in this create-agent workspace. "
            "Use inspect after adding package tools, then call a generated package tool with realistic arguments."
        ),
        entrypoint="agent_factory.create_agent.probe_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["inspect", "call"]},
                "tool_id": {"type": "string", "default": ""},
                "arguments": {"type": "object", "default": {}, "additionalProperties": True},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "tools": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "probe": {"type": "object", "additionalProperties": True},
                "diagnostics": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            },
            "required": ["action", "tools", "probe", "diagnostics"],
            "additionalProperties": False,
        },
        resources={
            "workspace": "create_agent_workspace",
        },
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.probe_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    action = str(arguments.get("action") or "").strip()
    if action == "inspect":
        return _inspect(workspace)
    if action == "call":
        return _call(workspace, tool_id=str(arguments.get("tool_id") or "").strip(), arguments=dict(arguments.get("arguments") or {}))
    raise ValueError(f"unsupported probe action: {action}")


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action == "inspect":
        return ToolRiskResult(action="allow", risk_level="low").model_dump(mode="json")
    if action == "call":
        return ToolRiskResult(
            action="allow",
            risk_level="low",
            reasons=["create-agent probe calls generated package tools through ToolExecutionGateway"],
        ).model_dump(mode="json")
    return ToolRiskResult(action="deny", risk_level="low", reasons=["unknown probe action"]).model_dump(mode="json")


def _inspect(workspace: CreateAgentWorkspace) -> dict[str, Any]:
    discovery = _discover(workspace)
    state = workspace.read_tool_probe_state()
    latest = state.latest_by_tool()
    tools = []
    current_digest = _package_digest(workspace.root)
    for spec in discovery.tool_specs:
        record = latest.get(spec.id)
        tools.append(
            {
                "tool_id": spec.id,
                "description": spec.description,
                "input_schema": spec.input_schema,
                "risk_level": spec.risk_level,
                "last_probe": _probe_record_summary(record, current_digest=current_digest) if record else None,
            }
        )
    return tool_envelope(
        {
            "action": "inspect",
            "tools": tools,
            "probe": {
                "required": bool(tools),
                "current_package_digest": current_digest,
                "guidance": "Call each generated package tool once with realistic input before final validation.",
            },
            "diagnostics": [_diagnostic_payload(item) for item in discovery.diagnostics],
        },
        summary=f"Discovered {len(tools)} package tool(s) for probe.",
    )


def _call(workspace: CreateAgentWorkspace, *, tool_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if not tool_id:
        raise ValueError("tool_id is required for probe call")
    discovery = _discover(workspace)
    specs = {spec.id: spec for spec in discovery.tool_specs}
    spec = specs.get(tool_id)
    if spec is None:
        raise ValueError(f"package tool is not available for probe: {tool_id}")
    before = _package_fingerprint(workspace.root)
    tool = ToolCompiler(
        package_root=workspace.root,
        resources=_probe_resources(workspace),
    ).compile(spec)
    observation = tool.invoke(arguments)
    after = _package_fingerprint(workspace.root)
    record = _record_from_observation(
        workspace=workspace,
        tool_id=tool_id,
        arguments=arguments,
        observation=observation if isinstance(observation, dict) else {"value": observation},
    )
    state = workspace.read_tool_probe_state()
    state.records.append(record)
    state = state.model_copy(update={"updated_at": datetime.now(UTC).isoformat()})
    workspace.write_tool_probe_state(state)
    changed_files = _changed_files(before, after)
    return tool_envelope(
        {
            "action": "call",
            "tools": [_tool_summary(spec)],
            "probe": {
                "tool_id": tool_id,
                "status": record.status,
                "observation_status": record.observation_status,
                "execution_status": record.execution_status,
                "contract_status": record.contract_status,
                "message": record.message,
                "output_summary": record.output_summary,
                "errors": record.errors,
                "changed_files": changed_files,
                "package_digest": record.package_digest,
            },
            "diagnostics": [_diagnostic_payload(item) for item in discovery.diagnostics],
        },
        evidence={
            "package_tool_probe": {
                "tool_id": tool_id,
                "status": record.status,
                "changed_files": changed_files,
            }
        },
        summary=f"Package tool probe {record.status}: {tool_id}.",
    )


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _discover(workspace: CreateAgentWorkspace):
    return PackageToolProvider().discover(ToolProviderContext(package_root=workspace.root))


def _probe_resources(workspace: CreateAgentWorkspace) -> dict[str, Any]:
    runtime_root = workspace.factory_dir / "tool_probe_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    return {
        "package_root": str(workspace.root),
        "runtime_root": str(runtime_root),
        "workspace_root": str(workspace.root),
        TOOL_OUTPUT_STORE_RESOURCE: ToolOutputStore(workspace.tool_outputs_path),
    }


def _record_from_observation(
    *,
    workspace: CreateAgentWorkspace,
    tool_id: str,
    arguments: dict[str, Any],
    observation: dict[str, Any],
) -> PackageToolProbeRecord:
    observation_status = str(observation.get("status") or "")
    execution_status = str(observation.get("execution_status") or "")
    contract_status = str(observation.get("contract_status") or "")
    errors = observation.get("errors")
    if not isinstance(errors, list):
        errors = []
    passed = observation_status == "completed" and execution_status == "completed" and contract_status == "valid"
    return PackageToolProbeRecord(
        tool_id=tool_id,
        arguments=arguments,
        package_digest=_package_digest(workspace.root),
        status="passed" if passed else "failed",
        observation_status=observation_status,
        execution_status=execution_status,
        contract_status=contract_status,
        message=str(observation.get("message") or "")[:500],
        output_summary=str(observation.get("output_summary") or "")[:500],
        errors=[str(item)[:500] for item in errors[:8]],
        probed_at=datetime.now(UTC).isoformat(),
    )


def _package_digest(root: Path) -> str:
    fingerprint = _package_fingerprint(root)
    return sha256(json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _probe_record_summary(record: PackageToolProbeRecord, *, current_digest: str) -> dict[str, Any]:
    return {
        "status": record.status,
        "stale": record.package_digest != current_digest,
        "observation_status": record.observation_status,
        "contract_status": record.contract_status,
        "message": record.message,
        "probed_at": record.probed_at,
    }


def _tool_summary(spec: ToolSpec) -> dict[str, Any]:
    return {
        "tool_id": spec.id,
        "description": spec.description,
        "input_schema": spec.input_schema,
        "risk_level": spec.risk_level,
    }


def _diagnostic_payload(item: Any) -> dict[str, Any]:
    return item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)


def _changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))
