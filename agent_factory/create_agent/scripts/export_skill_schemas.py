from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.create_agent.contract_catalog import required_contract_paths
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
    SessionContract,
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
    "16-session-contract/references/session_contract.schema.json": SessionContract,
}

EXAMPLE_EXPORTS: dict[str, BaseModel] = {
    "00-todo-control/examples/todo.minimal.json": TodoList(updated_at="1970-01-01T00:00:00+00:00"),
    "01-package-manifest/examples/agent_package.minimal.json": AgentPackageManifest(
        factory_run_id="factory_run_example",
        assembly_spec_path="assembly_spec.json",
        render_manifest_path="render_manifest.json",
        resources_path="resources.json",
        sandbox_contract_path="sandbox_contract.json",
        contracts=required_contract_paths(),
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
    "16-session-contract/examples/session_contract.minimal.json": SessionContract(),
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
    # Export runtime enumerations and builtin references
    for relative, content in sorted(_runtime_reference_exports().items()):
        target = skills_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(target)
    return written


def _runtime_reference_exports() -> dict[str, str]:
    """Generate reference markdown files from actual RuntimeKernel code."""
    from agent_factory.runtime_kernel.nodes.standard import (
        CognitiveAnswerNode, CognitiveClarifyNode, CognitivePlanNode,
        CognitiveReviewNode, CognitiveRouteNode, CognitiveStructuredNode,
        FinalizeNode, GovernanceApprovalGateNode, GovernancePostcheckNode,
        GovernancePrecheckNode, GovernanceRefusalGateNode, IngressNode,
        OperationalResourceProbeNode, OperationalToolCallNode,
        TerminalCloseNode, TerminalCommitNode,
    )
    from agent_factory.runtime_kernel.patterns.schema import (
        NodeType, PatternKind, PatternSlotType, StateMode,
    )
    from agent_factory.runtime_kernel.bindings.schema import (
        BindingType, HookPoint, ServiceKind,
    )
    from agent_factory.tooling.builtins.registry import IMPLEMENTED_BUILTIN_TOOL_IDS

    builtin_impls = [
        IngressNode, GovernancePrecheckNode, GovernancePostcheckNode,
        GovernanceApprovalGateNode, GovernanceRefusalGateNode,
        CognitiveClarifyNode, CognitivePlanNode, CognitiveRouteNode,
        CognitiveStructuredNode, CognitiveAnswerNode, CognitiveReviewNode,
        OperationalToolCallNode, OperationalResourceProbeNode,
        TerminalCommitNode, TerminalCloseNode, FinalizeNode,
    ]

    # Builtin node impl reference
    impl_lines = ["# Builtin Node Implementations", "",
                  "These are the ONLY valid `impl` values for pattern nodes (unless using a package node with `package.*` prefix).", ""]
    for node_cls in sorted(builtin_impls, key=lambda c: c.impl_id):
        node_type = getattr(node_cls, "node_type", "unknown")
        impl_lines.append(f"- `{node_cls.impl_id}` (type: {node_type})")
    impl_lines.append("")
    impl_lines.append("## Node Types")
    impl_lines.append("")
    impl_lines.append(f"Valid values: {', '.join(f'`{t}`' for t in _get_literal_args(NodeType))}")
    impl_lines.append("")
    impl_lines.append("## Edge `when` Conditions")
    impl_lines.append("")
    impl_lines.append("Extracted from builtin patterns:")
    edge_conditions = sorted({
        "always", "model.requests_tool", "model.ready_to_answer",
        "tool.completed", "tool.failed", "tool.interrupted",
        "policy.blocked", "policy.approval_required",
        "subgraph.done", "subgraph.need_more_input", "subgraph.blocked",
    })
    for cond in edge_conditions:
        impl_lines.append(f"- `{cond}`")
    impl_lines.append("")
    impl_lines.append("## Builtin Patterns")
    impl_lines.append("")
    impl_lines.append("- `react_agent` — Standard conversational tool-using agent (default choice)")
    impl_lines.append("- `clarify_then_act` — Ask for missing info before entering action flow")
    impl_lines.append("- `clarification_loop_v1` — Embeddable subgraph for clarification (not selectable as main)")
    impl_lines.append("")

    # Binding reference
    binding_lines = ["# Binding Reference", "",
                     "## binding_type values", ""]
    for bt in _get_literal_args(BindingType):
        binding_lines.append(f"- `{bt}`")
    binding_lines.append("")
    binding_lines.append("## ServiceKind values")
    binding_lines.append("")
    for sk in _get_literal_args(ServiceKind):
        binding_lines.append(f"- `{sk}`")
    binding_lines.append("")
    binding_lines.append("## HookPoint values")
    binding_lines.append("")
    for hp in _get_literal_args(HookPoint):
        binding_lines.append(f"- `{hp}`")
    binding_lines.append("")
    binding_lines.append("## PatternSlotType values")
    binding_lines.append("")
    for st in _get_literal_args(PatternSlotType):
        binding_lines.append(f"- `{st}`")
    binding_lines.append("")

    # Tools builtin IDs
    tools_lines = ["# Builtin Tool IDs", "",
                   "These tools are automatically available when `builtin_tools_enabled: true` in tools_contract.", ""]
    for tool_id in sorted(IMPLEMENTED_BUILTIN_TOOL_IDS):
        tools_lines.append(f"- `{tool_id}`")
    tools_lines.append("")

    return {
        "13-assembly-and-patterns/references/builtin_impls.md": "\n".join(impl_lines),
        "13-assembly-and-patterns/references/binding_reference.md": "\n".join(binding_lines),
        "08-tools-contract/references/builtin_tool_ids.md": "\n".join(tools_lines),
    }


def _get_literal_args(literal_type: Any) -> list[str]:
    """Extract string values from a typing.Literal type."""
    import typing
    args = typing.get_args(literal_type)
    return [str(a) for a in args]


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
