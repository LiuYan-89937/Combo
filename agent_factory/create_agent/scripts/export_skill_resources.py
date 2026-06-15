from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.create_agent.models import PackageValidationReport, SystemManufacturingState, initial_system_manufacturing_state
from agent_factory.create_agent.package_scaffold import materialize_empty_agent_package
from agent_factory.runtime_contracts.builtins import (
    default_artifact_contract,
    default_context_contract,
    default_dependencies_contract,
    default_knowledge_contract,
    default_memory_contract,
    default_model_contract,
    default_node_provider_contract,
    default_render_contract,
    default_resources_contract,
    default_sandbox_contract,
    default_scheduler_contract,
    default_scheduler_seed_contract,
    default_session_contract,
    default_state_contract,
    default_tools_contract,
    default_trace_contract,
)
from agent_factory.runtime_contracts.schema import AgentPackageManifest
from agent_factory.runtime_kernel.node_providers.package import PackageNodeManifest
from agent_factory.runtime_render import RenderManifest
from agent_factory.tooling.spec import ToolSpec


ROOT = Path(__file__).resolve().parents[3]
SKILLS_ROOT = ROOT / "agent_factory" / "create_agent" / "skills"
RESOURCE_IDS = {
    "00-manufacturing-control": "manufacturing_control",
    "01-package-identity-system": "package_identity",
    "02-model-system": "model_system",
    "03-session-system": "session_system",
    "04-state-system": "state_system",
    "05-resources-system": "resources_system",
    "06-context-system": "context_system",
    "07-memory-system": "memory_system",
    "08-knowledge-system": "knowledge_system",
    "09-tools-system": "tools_system",
    "10-package-tool-system": "package_tool_system",
    "11-node-provider-system": "node_provider_system",
    "12-assembly-pattern-system": "assembly_pattern_system",
    "13-render-event-system": "render_event_system",
    "14-scheduler-system": "scheduler_system",
    "15-scheduler-seed-system": "scheduler_seed_system",
    "16-trace-artifact-system": "trace_artifact_system",
    "17-final-validation-repair": "final_validation",
}
CAPABILITY_EXAMPLE_SKILLS = frozenset(
    {
        "10-package-tool-system",
        "11-node-provider-system",
        "12-assembly-pattern-system",
        "15-scheduler-seed-system",
        "17-final-validation-repair",
    }
)
SCAFFOLD_RUN_ID = "factory_run"
SCAFFOLD_USER_INPUT = "Generated RuntimeKernel AgentPackage."
STATIC_EXAMPLE_UPDATED_AT = "2026-01-01T00:00:00+00:00"


def main() -> None:
    scaffold = _scaffold_example_files()
    exports = {
        "00-manufacturing-control": _export(
            title="Manufacturing control state",
            files={".factory/system_state.json": (SystemManufacturingState, _manufacturing_control_example())},
        ),
        "01-package-identity-system": _export(
            title="Agent package manifest",
            files={"agent_package.json": (AgentPackageManifest, scaffold["agent_package.json"])},
        ),
        "02-model-system": _export(
            title="Model, dependency, and sandbox contracts",
            files={
                "contracts/model.json": (type(default_model_contract()), scaffold["contracts/model.json"]),
                "contracts/dependencies.json": (type(default_dependencies_contract()), scaffold["contracts/dependencies.json"]),
                "contracts/sandbox.json": (type(default_sandbox_contract()), scaffold["contracts/sandbox.json"]),
                "sandbox_contract.json": (dict, scaffold["sandbox_contract.json"]),
            },
        ),
        "03-session-system": _export(
            title="Session contract",
            files={"contracts/session.json": (type(default_session_contract()), default_session_contract())},
        ),
        "04-state-system": _export(
            title="State contract and state files",
            files={
                "contracts/state.json": (type(default_state_contract()), default_state_contract()),
                "state/package.schema.json": (dict, {"type": "object", "additionalProperties": True}),
                "state/package.initial.json": (dict, {}),
            },
        ),
        "05-resources-system": _export(
            title="Resources contract and resource facts",
            files={
                "contracts/resources.json": (type(default_resources_contract()), scaffold["contracts/resources.json"]),
                "resources.json": (dict, scaffold["resources.json"]),
                ".factory/resources.json": (
                    dict,
                    {"version": "resource_facts.v0", "facts": []},
                ),
            },
        ),
        "06-context-system": _export(
            title="Context contract",
            files={"contracts/context.json": (type(default_context_contract()), default_context_contract())},
        ),
        "07-memory-system": _export(
            title="Memory contract",
            files={"contracts/memory.json": (type(default_memory_contract()), default_memory_contract())},
        ),
        "08-knowledge-system": _export(
            title="Knowledge contract",
            files={"contracts/knowledge.json": (type(default_knowledge_contract()), default_knowledge_contract())},
        ),
        "09-tools-system": _export(
            title="Tools contract",
            files={"contracts/tools.json": (type(default_tools_contract()), default_tools_contract())},
        ),
        "10-package-tool-system": _export(
            title="Package tool manifest",
            files=_package_tool_example_files(),
        ),
        "11-node-provider-system": _export(
            title="Node provider contract and package node manifest",
            files={
                "contracts/node_provider.json": (type(default_node_provider_contract()), default_node_provider_contract()),
                "nodes/<node_id>/manifest.json": (PackageNodeManifest, _package_node_example()),
            },
        ),
        "12-assembly-pattern-system": _export(
            title="Assembly spec capability increment",
            files={
                "assembly_spec.json": (AgentAssemblySpec, _assembly_with_tool_binding_example()),
            },
        ),
        "13-render-event-system": _export(
            title="Render contract and manifest",
            files={
                "contracts/render.json": (type(default_render_contract()), scaffold["contracts/render.json"]),
                "render_manifest.json": (RenderManifest, scaffold["render_manifest.json"]),
            },
        ),
        "14-scheduler-system": _export(
            title="Scheduler contract",
            files={"contracts/scheduler.json": (type(default_scheduler_contract()), default_scheduler_contract())},
        ),
        "15-scheduler-seed-system": _export(
            title="Scheduler seed contract",
            files={"contracts/scheduler_seed.json": (type(default_scheduler_seed_contract()), _scheduler_seed_capability_example())},
        ),
        "16-trace-artifact-system": _export(
            title="Trace and artifact contracts",
            files={
                "contracts/trace.json": (type(default_trace_contract()), default_trace_contract()),
                "contracts/artifact.json": (type(default_artifact_contract()), default_artifact_contract()),
            },
        ),
        "17-final-validation-repair": _export(
            title="Package validation report",
            files={".factory/validation.json": (PackageValidationReport, PackageValidationReport(package_root="."))},
        ),
    }
    for skill_name, payload in exports.items():
        system_id = RESOURCE_IDS[skill_name]
        skill_root = SKILLS_ROOT / skill_name
        _write_json(skill_root / "references" / f"{system_id}.schema.json", payload["schema"])
        example_path = skill_root / "examples" / f"{system_id}.capability.json"
        if skill_name in CAPABILITY_EXAMPLE_SKILLS:
            _write_json(example_path, payload["example"])
        elif example_path.exists():
            example_path.unlink()


def _export(*, title: str, files: dict[str, tuple[type[Any], Any]]) -> dict[str, Any]:
    if len(files) == 1:
        model_or_type, example = next(iter(files.values()))
        return {
            "schema": _schema_for(model_or_type, title=title),
            "example": _dump_example(example),
        }
    return {
        "schema": {
            "type": "object",
            "title": title,
            "description": "System resource map. Each property is the schema for the named package file.",
            "additionalProperties": False,
            "properties": {path: _schema_for(model, title=path) for path, (model, _example) in files.items()},
            "required": list(files),
        },
        "example": {path: _dump_example(example) for path, (_model, example) in files.items()},
    }


def _scheduler_seed_capability_example() -> Any:
    contract = default_scheduler_seed_contract()
    config = type(contract.config).model_validate(
        {
            "seeds": [
                {
                    "seed_id": "daily_runtime_task",
                    "title": "Daily runtime task",
                    "human_schedule": "Every weekday at 09:00 Asia/Shanghai",
                    "schedule_type": "cron",
                    "schedule_expr": "0 9 * * 1-5",
                    "timezone": "Asia/Shanghai",
                    "target": {
                        "target_type": "graph_run",
                        "payload": {
                            "message": "Run the scheduled agent task using the package's implemented runtime capability."
                        },
                    },
                    "task_content": "Run the package's implemented scheduled task and produce the configured user-facing output.",
                    "enabled_on_apply": True,
                    "failure_policy": {"enabled": True, "max_consecutive_failures": 3, "action": "pause"},
                    "feedback": {"enabled": True, "mode": "llm_summary"},
                    "source_slot_id": "user_confirmed_schedule",
                    "concurrency_policy": "skip",
                    "max_concurrent_runs": 1,
                    "timeout_seconds": 900,
                    "unattended_policy": "deny_if_approval_required",
                }
            ]
        }
    )
    return contract.model_copy(
        update={
            "config": config
        }
    )


def _schema_for(model_or_type: type[Any], *, title: str) -> dict[str, Any]:
    if hasattr(model_or_type, "model_json_schema"):
        schema = model_or_type.model_json_schema()
        schema["title"] = title
        return schema
    if model_or_type is str:
        return {
            "type": "string",
            "title": title,
        }
    return {
        "type": "object",
        "title": title,
        "additionalProperties": True,
    }


def _dump_example(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return value


def _scaffold_example_files() -> dict[str, Any]:
    with TemporaryDirectory() as tmp:
        package_root = Path(tmp)
        materialize_empty_agent_package(
            package_root,
            factory_run_id=SCAFFOLD_RUN_ID,
            user_input=SCAFFOLD_USER_INPUT,
        )
        result: dict[str, Any] = {}
        for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
            relative = path.relative_to(package_root).as_posix()
            result[relative] = json.loads(path.read_text(encoding="utf-8"))
        return result


def _package_tool_example_files() -> dict[str, tuple[type[Any], Any]]:
    tool_spec = ToolSpec(
        id="package_action",
        description="Performs one package-defined runtime action.",
        entrypoint="python:tools/package_action/tool.py:run",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
            "additionalProperties": True,
        },
        risk_level="low",
    )
    return {
        "tools/package_action/manifest.json": (ToolSpec, tool_spec),
        "tools/package_action/tool.py": (
            str,
            (
                "from agent_factory.tooling.envelope import tool_envelope\n\n\n"
                "def run(arguments, resources):\n"
                "    query = str(arguments.get(\"query\") or \"\").strip()\n"
                "    result = query if query else \"No query provided.\"\n"
                "    return tool_envelope(\n"
                "        {\"result\": result},\n"
                "        evidence={\"tool_id\": \"package_action\"},\n"
                "        summary=\"Package action completed.\",\n"
                "    )\n"
            ),
        ),
        "contracts/tools.json": (
            type(default_tools_contract()),
            {
                "type": "tools",
                "version": "tools_contract.v0",
                "enabled": True,
                "config": {
                    "builtin_tools_enabled": True,
                    "builtin_tool_ids": [],
                    "package_tools_enabled": True,
                },
            },
        ),
        "assembly_spec.json#tools_item": (ToolSpec, tool_spec),
    }


def _manufacturing_control_example() -> SystemManufacturingState:
    state = initial_system_manufacturing_state()
    active = state.stages[0]
    next_stage = state.stages[1]
    return state.model_copy(
        update={
            "stages": [active, next_stage],
            "active_focus_id": active.system_id,
            "updated_at": STATIC_EXAMPLE_UPDATED_AT,
        }
    )


def _tool_spec_example() -> ToolSpec:
    return ToolSpec(
        id="package_action",
        description="Performs one package-defined runtime action.",
        entrypoint="python:tools/package_action/tool.py:run",
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={"type": "object", "additionalProperties": True},
    )


def _package_node_example() -> PackageNodeManifest:
    return PackageNodeManifest(
        impl_id="package.example_node",
        node_type="operational",
        entrypoint="nodes/example_node/node.py:run",
        description="Package node description.",
    )


def _assembly_with_tool_binding_example() -> AgentAssemblySpec:
    return AgentAssemblySpec.model_validate(
        {
            "schema_version": "0.1",
            "agent": {
                "id": "generated_agent",
                "name": "Generated Agent",
                "description": "Generated RuntimeKernel AgentPackage.",
                "version": "0.1.0",
            },
            "runtime": {
                "pattern_id": "react_agent",
                "user_config": {},
                "agent_config": {},
            },
            "bindings": {
                "node_bindings": [
                    {
                        "binding_id": "answer_prompt",
                        "binding_type": "prompt",
                        "target": {"node_id": "answer", "impl": "standard.answer"},
                        "payload": {
                            "prompt_id": "answer_prompt",
                            "template": "Use the user's request, runtime context, and approved tools to produce a useful answer.",
                            "variables": [],
                        },
                    },
                    {
                        "binding_id": "answer_tool_access",
                        "binding_type": "tool_access",
                        "target": {"node_id": "answer", "impl": "standard.answer"},
                        "payload": {
                            "allowed_tool_ids": ["package_action"],
                            "approval_policy": "standard",
                        },
                    },
                    {
                        "binding_id": "answer_model_operation",
                        "binding_type": "model_operation",
                        "target": {"node_id": "answer", "impl": "standard.answer"},
                        "payload": {
                            "operation": "tool_bound_chat",
                            "model_role": "main",
                            "output_schema": {
                                "type": "object",
                                "properties": {"answer": {"type": "string"}},
                                "required": ["answer"],
                                "additionalProperties": True,
                            },
                            "write_target": {"section": "context"},
                            "max_attempts": 3,
                            "prompt_id": "answer_prompt",
                        },
                    },
                ],
            },
            "tools": [_tool_spec_example().model_dump(mode="json", exclude_none=True)],
            "output": {"citations_required": False, "format": "text"},
        }
    )
def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
