from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.create_agent.models import PackageValidationReport, TodoList
from agent_factory.runtime_contracts.schema import (
    AgentPackageManifest,
    ContextContract,
    KnowledgeContract,
    MemoryContract,
    ResourcesContract,
    RuntimeContractEnvelope,
    SchedulerContract,
    SchedulerSeedContract,
    StateContract,
    ToolsContract,
    TraceContract,
)
from agent_factory.runtime_kernel.node_providers.package import PackageNodeManifest
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec
from agent_factory.runtime_render import RenderManifest
from agent_factory.tooling.spec import ToolSpec


SKILLS_ROOT = Path(__file__).resolve().parents[1] / "skills"
SCHEMA_EXPORTS: dict[str, type[BaseModel]] = {
    "00-todo-control/references/todo.schema.json": TodoList,
    "01-package-manifest/references/agent_package.schema.json": AgentPackageManifest,
    "02-runtime-contract-index/references/contract_index.schema.json": RuntimeContractEnvelope,
    "03-context-contract/references/context_contract.schema.json": ContextContract,
    "04-memory-contract/references/memory_contract.schema.json": MemoryContract,
    "05-knowledge-contract/references/knowledge_contract.schema.json": KnowledgeContract,
    "06-trace-contract/references/trace_contract.schema.json": TraceContract,
    "07-state-resources-contract/references/state_contract.schema.json": StateContract,
    "07-state-resources-contract/references/resources_contract.schema.json": ResourcesContract,
    "08-tools-contract/references/tools_contract.schema.json": ToolsContract,
    "09-package-tools/references/package_tool.schema.json": ToolSpec,
    "09-package-tools/references/tool_contract.schema.json": ToolsContract,
    "10-package-nodes/references/package_node.schema.json": PackageNodeManifest,
    "11-scheduler-contract/references/scheduler_contract.schema.json": SchedulerContract,
    "12-scheduler-seeds/references/scheduler_seed.schema.json": SchedulerSeedContract,
    "13-assembly-and-patterns/references/assembly_spec.schema.json": AgentAssemblySpec,
    "13-assembly-and-patterns/references/pattern.schema.json": GraphPatternSpec,
    "14-render-and-events/references/render_manifest.schema.json": RenderManifest,
    "15-validation-repair/references/validation_report.schema.json": PackageValidationReport,
}

EXAMPLE_EXPORTS: dict[str, BaseModel] = {
    "00-todo-control/examples/todo.minimal.json": TodoList(updated_at="1970-01-01T00:00:00+00:00"),
    "01-package-manifest/examples/agent_package.minimal.json": AgentPackageManifest(
        factory_run_id="factory_run_example",
        assembly_spec_path="assembly_spec.json",
        render_manifest_path="render_manifest.json",
        resources_path="resources.json",
        sandbox_contract_path="sandbox_contract.json",
        contracts={
            "artifact": "contracts/artifact.json",
            "context": "contracts/context.json",
            "dependencies": "contracts/dependencies.json",
            "knowledge": "contracts/knowledge.json",
            "model": "contracts/model.json",
            "node_provider": "contracts/node_provider.json",
            "render": "contracts/render.json",
            "resources": "contracts/resources.json",
            "sandbox": "contracts/sandbox.json",
            "scheduler": "contracts/scheduler.json",
            "session": "contracts/session.json",
            "state": "contracts/state.json",
            "tools": "contracts/tools.json",
            "trace": "contracts/trace.json",
        },
        patterns=["patterns/main.yaml"],
    ),
    "02-runtime-contract-index/examples/runtime_contract_index.minimal.json": RuntimeContractEnvelope(
        type="tools",
        version="tools_contract.v0",
    ),
    "03-context-contract/examples/context_contract.minimal.json": ContextContract(),
    "04-memory-contract/examples/memory_contract.minimal.json": MemoryContract(),
    "05-knowledge-contract/examples/knowledge_contract.minimal.json": KnowledgeContract(),
    "06-trace-contract/examples/trace_contract.minimal.json": TraceContract(),
    "07-state-resources-contract/examples/state_contract.minimal.json": StateContract(),
    "07-state-resources-contract/examples/resources_contract.minimal.json": ResourcesContract(),
    "08-tools-contract/examples/tools_contract.minimal.json": ToolsContract(),
    "09-package-tools/examples/package_tool.minimal.json": ToolSpec(
        id="example_tool",
        description="Package-specific deterministic operation.",
        entrypoint="tools/example_tool/tool.py:run",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        output_schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
    ),
    "09-package-tools/examples/tool_contract.minimal.json": ToolsContract(),
    "10-package-nodes/examples/package_node.minimal.json": PackageNodeManifest(
        impl_id="package.example_node",
        node_type="operational",
        entrypoint="nodes/example_node/node.py:run",
        description="Package-local deterministic graph logic.",
    ),
    "11-scheduler-contract/examples/scheduler_contract.minimal.json": SchedulerContract(),
    "12-scheduler-seeds/examples/scheduler_seed.minimal.json": SchedulerSeedContract(),
    "13-assembly-and-patterns/examples/assembly_spec.minimal.json": AgentAssemblySpec(
        agent={"id": "agent_example", "name": "Example Agent"},
        runtime={"pattern_id": "main"},
    ),
    "13-assembly-and-patterns/examples/pattern.minimal.json": GraphPatternSpec(
        pattern_id="main",
        kind="main",
        embeddable=False,
        version=1,
        name="Main",
        description="Minimal executable pattern.",
        entry_node="ingress",
        nodes=[
            {"id": "ingress", "type": "reserved", "impl": "ingress"},
            {"id": "finalize", "type": "terminal", "impl": "finalize"},
        ],
        edges=[{"from": "ingress", "to": "finalize", "when": "always"}],
        termination={"success_nodes": ["finalize"]},
    ),
    "14-render-and-events/examples/render_manifest.minimal.json": RenderManifest(
        graph_id="agent_example",
        nodes={
            "ingress": {
                "node_id": "ingress",
                "label": "Ingress",
                "kind": "reserved",
                "purpose": "Accept input.",
                "doing": "Preparing the run.",
                "expected_output": "Initial state is ready.",
            },
            "finalize": {
                "node_id": "finalize",
                "label": "Finalize",
                "kind": "terminal",
                "purpose": "Complete the run.",
                "doing": "Finalizing output.",
                "expected_output": "Run is complete.",
            },
        },
    ),
    "15-validation-repair/examples/validation_report.minimal.json": PackageValidationReport(
        package_root=".",
        skipped=True,
        summary="Validation report example.",
    ),
}


def export_skill_schemas(*, skills_root: Path = SKILLS_ROOT) -> list[Path]:
    written: list[Path] = []
    for relative, model in sorted(SCHEMA_EXPORTS.items()):
        target = skills_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_schema_text(model), encoding="utf-8")
        written.append(target)
    for relative, model in sorted(EXAMPLE_EXPORTS.items()):
        target = skills_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_example_text(model), encoding="utf-8")
        written.append(target)
    return written


def _schema_text(model: type[BaseModel]) -> str:
    schema = model.model_json_schema()
    return json.dumps(_normalize(schema), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _example_text(model: BaseModel) -> str:
    payload = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(_normalize(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def main() -> None:
    for path in export_skill_schemas():
        print(path.relative_to(SKILLS_ROOT))


if __name__ == "__main__":
    main()
