from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.factory_package.schemas import RuntimeDesignOutput, RuntimeDesignValidationReport
from agent_factory.runtime_kernel.nodes.catalog import NODE_IMPLEMENTATION_IDS, NODE_TYPES
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry
from agent_factory.runtime_kernel.patterns.validator import (
    ALLOWED_EDGE_CONDITIONS,
    ALLOWED_REQUIRED_CAPABILITIES,
)


SUPPORTED_RUNTIME_CONTRACTS = {
    "artifact",
    "context",
    "dependencies",
    "knowledge",
    "memory",
    "model",
    "node_provider",
    "render",
    "resources",
    "sandbox",
    "scheduler",
    "session",
    "state",
    "tools",
    "trace",
}


def runtime_kernel_catalog_payload() -> dict[str, Any]:
    registry = _pattern_registry()
    top_level_patterns = registry.list_pattern_catalog(include_embeddable=False)
    return {
        "patterns": [
            {
                "catalog": item.model_dump(mode="json"),
                "structure": registry.get_structure_summary(item.pattern_id).model_dump(mode="json"),
            }
            for item in top_level_patterns
        ],
        "pattern_selection_contract": {
            "design_mode": "Always reuse_pattern.",
            "topology": "Runtime Design schema does not include edges, interrupts, termination, or custom pattern YAML. Preset pattern owns graph semantics.",
            "nodes": "Only describe existing selected pattern nodes that need prompt/tool/state/context strategy.",
            "slots": "Use pattern_slots with typed binding objects. Slot ids and slot types must match the selected pattern catalog exactly.",
        },
        "allowed_node_types": sorted(NODE_TYPES),
        "allowed_node_impls": sorted(NODE_IMPLEMENTATION_IDS),
        "allowed_edge_conditions": sorted(ALLOWED_EDGE_CONDITIONS),
        "allowed_pattern_capabilities": sorted(ALLOWED_REQUIRED_CAPABILITIES),
        "supported_runtime_contracts": sorted(SUPPORTED_RUNTIME_CONTRACTS),
        "package_local_node_rules": {
            "provider_id": "builtin.package_nodes",
            "impl_id_prefix": "package.",
            "manifest_path": "nodes/<node_id>/manifest.json",
            "entrypoint": "node.py:run",
        },
    }


def validate_runtime_design(design: RuntimeDesignOutput) -> RuntimeDesignValidationReport:
    registry = _pattern_registry()
    errors: list[str] = []
    warnings: list[str] = []
    supported_contracts = set(SUPPORTED_RUNTIME_CONTRACTS)
    unknown_contracts = sorted(set(design.required_contracts).difference(supported_contracts))
    if unknown_contracts:
        errors.append(f"unknown runtime contracts: {', '.join(unknown_contracts)}")

    selected_pattern_summary: dict[str, object] = {}
    selected_pattern_nodes: dict[str, Any] = {}
    selected_pattern_slots: dict[str, Any] = {}
    reference_node_ids: set[str] = set()
    try:
        selected = registry.get(design.selected_pattern_id)
        if selected.kind != "main" or selected.embeddable:
            errors.append(f"selected_pattern_id must reference a top-level pattern: {selected.pattern_id}")
        selected_pattern_summary = registry.get_structure_summary(selected.pattern_id).model_dump(mode="json")
        selected_pattern_nodes = {node.id: node for node in selected.nodes}
        selected_pattern_slots = {slot.slot_id: slot for slot in selected.slots}
        reference_node_ids = set(selected_pattern_nodes)
    except Exception as exc:
        errors.append(f"unknown selected_pattern_id: {design.selected_pattern_id} ({exc})")

    package_impl_ids = {item.impl_id for item in design.package_nodes_to_generate}
    package_impl_ids.update(
        node.package_node_impl_id
        for node in design.nodes
        if node.package_node_impl_id
    )
    package_impl_ids = {item for item in package_impl_ids if item}
    known_impls = set(package_impl_ids)

    for node in design.nodes:
        pattern_node = selected_pattern_nodes.get(node.node_id)
        if pattern_node is None:
            errors.append(f"node plan references node outside selected pattern: {node.node_id}")
            continue
        if node.node_type != pattern_node.type:
            errors.append(
                f"node {node.node_id} type must match selected pattern: {pattern_node.type}, got {node.node_type}"
            )
        if node.impl != pattern_node.impl:
            errors.append(
                f"node {node.node_id} impl must match selected pattern: {pattern_node.impl}, got {node.impl}"
            )
        if node.impl not in NODE_IMPLEMENTATION_IDS and node.impl not in known_impls and node.impl != "pattern_ref":
            errors.append(f"unknown node impl for {node.node_id}: {node.impl}")
        if node.node_type not in NODE_TYPES:
            errors.append(f"unknown node type for {node.node_id}: {node.node_type}")
        if node.requires_tools and "tools" not in design.required_contracts:
            errors.append(f"node {node.node_id} requires tools but required_contracts does not include tools")
        if node.requires_package_node and node.impl != node.package_node_impl_id:
            errors.append(f"package node {node.node_id} must use impl equal to package_node_impl_id")

    declared_package_nodes = {item.impl_id: item.node_id for item in design.package_nodes_to_generate}
    for node in design.nodes:
        if node.requires_package_node and node.package_node_impl_id not in declared_package_nodes:
            errors.append(f"package node {node.node_id} is missing from package_nodes_to_generate")

    structured_by_node = {item.produced_by_node for item in design.structured_outputs}
    for node_id in structured_by_node:
        if node_id not in reference_node_ids:
            errors.append(f"structured output references unknown node: {node_id}")
        elif selected_pattern_nodes[node_id].impl != "cognitive.structured":
            errors.append(f"structured output references non-structured preset node: {node_id}")
    for node in design.nodes:
        if node.requires_structured_output and node.node_id not in structured_by_node:
            errors.append(f"node {node.node_id} requires structured output but no structured_outputs item references it")

    if any(node.requires_tools for node in design.nodes) and not any(
        item.impl == "operational.tool_call" for item in selected_pattern_nodes.values()
    ):
        errors.append(f"selected pattern {design.selected_pattern_id} has no operational.tool_call node")

    emitted_slot_ids = {slot.slot_id for slot in design.pattern_slots}
    for slot_id, catalog_slot in selected_pattern_slots.items():
        if bool(catalog_slot.required) and slot_id not in emitted_slot_ids:
            errors.append(f"required pattern slot is missing from runtime design: {slot_id}")
    unknown_slot_ids = sorted(emitted_slot_ids.difference(selected_pattern_slots))
    if unknown_slot_ids:
        errors.append("runtime design emitted slots outside selected pattern: " + ", ".join(unknown_slot_ids))

    for slot in design.pattern_slots:
        catalog_slot = selected_pattern_slots.get(slot.slot_id)
        if catalog_slot is not None and slot.slot_type != catalog_slot.slot_type:
            errors.append(
                f"pattern slot {slot.slot_id} type must match selected pattern: "
                f"{catalog_slot.slot_type}, got {slot.slot_type}"
            )
        unknown_nodes = sorted(set(slot.required_by_nodes).difference(reference_node_ids))
        if unknown_nodes:
            errors.append(f"pattern slot {slot.slot_id} references unknown nodes: " + ", ".join(unknown_nodes))
        catalog_node_id = getattr(catalog_slot, "node_id", None) if catalog_slot is not None else None
        if catalog_node_id and slot.required_by_nodes and catalog_node_id not in slot.required_by_nodes:
            errors.append(f"pattern slot {slot.slot_id} must include catalog node {catalog_node_id}")

    if design.state_namespaces and "state" not in design.required_contracts:
        errors.append("state_namespaces requires state contract")
    namespace_counts: dict[str, int] = {}
    for namespace in design.state_namespaces:
        namespace_counts[namespace.namespace] = namespace_counts.get(namespace.namespace, 0) + 1
    duplicate_namespaces = sorted(namespace for namespace, count in namespace_counts.items() if count > 1)
    if duplicate_namespaces:
        errors.append("duplicate state namespaces: " + ", ".join(duplicate_namespaces))
    if design.package_nodes_to_generate and "node_provider" not in design.required_contracts:
        errors.append("package_nodes_to_generate requires node_provider contract")
    if design.structured_outputs and "model" not in design.required_contracts:
        errors.append("structured_outputs requires model contract")
    if "trace" not in design.required_contracts:
        warnings.append("trace contract should normally be included for manufactured AgentPackages")

    return RuntimeDesignValidationReport(
        status="invalid" if errors else "valid",
        design_mode=design.design_mode,
        selected_pattern_id=design.selected_pattern_id,
        candidate_pattern_id=None,
        errors=errors,
        warnings=warnings,
        validated_pattern_summary=selected_pattern_summary,
    )


def validation_feedback_text(report: RuntimeDesignValidationReport | None) -> str:
    if report is None:
        return "无。"
    if report.status == "valid":
        return "上一轮 Runtime Design 已通过 Kernel 预校验。"
    lines = ["上一轮 Runtime Design 未通过 Kernel 预校验，请修正以下问题："]
    lines.extend(f"- {item}" for item in report.errors)
    if report.warnings:
        lines.append("警告：")
        lines.extend(f"- {item}" for item in report.warnings)
    return "\n".join(lines)


def runtime_design_message(design: RuntimeDesignOutput, report: RuntimeDesignValidationReport) -> str:
    lines = [
        "Runtime Design 已完成。",
        "",
        "运行结构：复用预设 pattern",
        f"图意图：{design.graph_intent}",
        f"选择 pattern：{design.selected_pattern_id}",
    ]
    if design.nodes:
        lines.extend(["", "节点设计："])
        for node in design.nodes:
            lines.append(f"- {node.node_id} / {node.impl}：{node.purpose}")
    if design.pattern_slots:
        lines.extend(["", "Pattern 槽位绑定："])
        for slot in design.pattern_slots:
            lines.append(f"- {slot.slot_id} / {slot.slot_type}：{slot.binding_strategy}")
    if design.required_contracts:
        lines.extend(["", "需要接入的基础能力：", ", ".join(design.required_contracts)])
    if design.state_namespaces:
        lines.extend(["", "运行状态 namespace："])
        for namespace in design.state_namespaces:
            lines.append(f"- {namespace.namespace}：{namespace.purpose}")
    if design.package_nodes_to_generate:
        lines.extend(["", "后续需要生成的 package-local node："])
        for item in design.package_nodes_to_generate:
            lines.append(f"- {item.impl_id}：{item.purpose}")
    if design.structured_outputs:
        lines.extend(["", "结构化输出："])
        for item in design.structured_outputs:
            lines.append(f"- {item.output_id} / {item.produced_by_node}：{item.schema_summary}")
    if report.warnings:
        lines.extend(["", "校验提示：", *[f"- {item}" for item in report.warnings]])
    if design.design_summary_text:
        lines.extend(["", "设计说明：", design.design_summary_text])
    return "\n".join(lines).strip()


def _pattern_registry() -> PatternRegistry:
    builtins_dir = Path(__file__).resolve().parents[1] / "runtime_kernel" / "patterns" / "builtins"
    return PatternRegistry(builtins_dir=builtins_dir)
