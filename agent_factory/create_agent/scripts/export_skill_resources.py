from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.create_agent.contract_catalog import required_contract_paths
from agent_factory.create_agent.models import PackageValidationReport, SystemManufacturingState, initial_system_manufacturing_state
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
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec
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


def main() -> None:
    exports = {
        "00-manufacturing-control": _export(
            title="Manufacturing control state",
            files={".factory/system_state.json": (SystemManufacturingState, _manufacturing_control_example())},
        ),
        "01-package-identity-system": _export(
            title="Agent package manifest",
            files={"agent_package.json": (AgentPackageManifest, _agent_package_example())},
        ),
        "02-model-system": _export(
            title="Model, dependency, and sandbox contracts",
            files={
                "contracts/model.json": (type(default_model_contract()), default_model_contract()),
                "contracts/dependencies.json": (type(default_dependencies_contract()), default_dependencies_contract()),
                "contracts/sandbox.json": (type(default_sandbox_contract()), default_sandbox_contract()),
                "sandbox_contract.json": (dict, {"version": "sandbox_contract.v0", "resources": {}}),
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
                "contracts/resources.json": (type(default_resources_contract()), default_resources_contract()),
                "resources.json": (dict, {}),
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
            files={"tools/<tool_id>/manifest.json": (ToolSpec, _tool_spec_example())},
        ),
        "11-node-provider-system": _export(
            title="Node provider contract and package node manifest",
            files={
                "contracts/node_provider.json": (type(default_node_provider_contract()), default_node_provider_contract()),
                "nodes/<node_id>/manifest.json": (PackageNodeManifest, _package_node_example()),
            },
        ),
        "12-assembly-pattern-system": _export(
            title="Assembly spec and custom pattern",
            files={
                "assembly_spec.json": (AgentAssemblySpec, _assembly_example()),
                "patterns/<pattern_id>.yaml": (GraphPatternSpec, _pattern_example()),
            },
        ),
        "13-render-event-system": _export(
            title="Render contract and manifest",
            files={
                "contracts/render.json": (type(default_render_contract()), default_render_contract()),
                "render_manifest.json": (RenderManifest, _render_manifest_example()),
            },
        ),
        "14-scheduler-system": _export(
            title="Scheduler contract",
            files={"contracts/scheduler.json": (type(default_scheduler_contract()), default_scheduler_contract())},
        ),
        "15-scheduler-seed-system": _export(
            title="Scheduler seed contract",
            files={"contracts/scheduler_seed.json": (type(default_scheduler_seed_contract()), default_scheduler_seed_contract())},
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
        _write_json(skill_root / "examples" / f"{system_id}.minimal.json", payload["example"])


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


def _schema_for(model_or_type: type[Any], *, title: str) -> dict[str, Any]:
    if hasattr(model_or_type, "model_json_schema"):
        schema = model_or_type.model_json_schema()
        schema["title"] = title
        return schema
    return {
        "type": "object",
        "title": title,
        "additionalProperties": True,
    }


def _dump_example(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    return value


def _agent_package_example() -> AgentPackageManifest:
    return AgentPackageManifest(
        version="agent_package.v0",
        factory_run_id="factory_run",
        agent={
            "id": "generated_agent",
            "name": "Generated Agent",
            "description": "Generated RuntimeKernel AgentPackage.",
            "version": "0.1.0",
        },
        runtime={"pattern_id": "react_agent"},
        assembly_spec_path="assembly_spec.json",
        render_manifest_path="render_manifest.json",
        resources_path="resources.json",
        sandbox_contract_path="sandbox_contract.json",
        contracts=required_contract_paths(),
        patterns=[],
    )


def _manufacturing_control_example() -> SystemManufacturingState:
    state = initial_system_manufacturing_state()
    active = state.stages[0]
    next_stage = state.stages[1]
    return state.model_copy(update={"stages": [active, next_stage], "active_focus_id": active.system_id})


def _tool_spec_example() -> ToolSpec:
    return ToolSpec(
        id="package_tool",
        description="Package tool description.",
        entrypoint="python:tools/package_tool/tool.py:run",
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


def _assembly_example() -> AgentAssemblySpec:
    return AgentAssemblySpec(
        agent={"id": "generated_agent", "name": "Generated Agent"},
        runtime={"pattern_id": "react_agent"},
    )


def _pattern_example() -> GraphPatternSpec:
    return GraphPatternSpec(
        pattern_id="custom_pattern",
        kind="main",
        embeddable=False,
        version=1,
        name="Custom Pattern",
        description="Custom package pattern.",
        entry_node="ingress",
        nodes=[
            {"id": "ingress", "type": "reserved", "impl": "reserved.ingress"},
            {"id": "finalize", "type": "reserved", "impl": "reserved.finalize"},
        ],
        edges=[{"from": "ingress", "to": "finalize", "when": "always"}],
        termination={"success_nodes": ["finalize"], "failure_nodes": []},
    )


def _render_manifest_example() -> RenderManifest:
    return RenderManifest(
        graph_id="react_agent",
        nodes={
            "answer": {
                "node_id": "answer",
                "label": "Answer",
                "kind": "cognitive",
                "purpose": "Generate an answer.",
                "doing": "Running the answer node.",
                "expected_output": "Final response.",
                "visible_to_user": True,
            }
        },
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
