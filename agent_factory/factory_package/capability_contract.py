from __future__ import annotations

from typing import Any

from agent_factory.factory_package.schemas import (
    CapabilityContractOutput,
    CapabilityContractValidationReport,
    RuntimeDesignOutput,
)
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
    default_session_contract,
    default_state_contract,
    default_tools_contract,
    default_trace_contract,
)
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_contracts.schema import (
    NodeProviderContractConfig,
    NodeProviderReference,
    REQUIRED_AGENT_PACKAGE_CONTRACTS,
    StateContractConfig,
)


STANDARD_CAPABILITY_SYSTEMS = (
    "session",
    "model",
    "state",
    "tools",
    "memory",
    "context",
    "knowledge",
    "scheduler",
    "trace",
    "resources",
    "sandbox",
    "artifact",
    "node_provider",
    "dependencies",
    "render",
)


def capability_contract_catalog_payload(runtime_design: RuntimeDesignOutput) -> dict[str, Any]:
    return {
        "standard_capability_systems": list(STANDARD_CAPABILITY_SYSTEMS),
        "required_agent_package_contracts": sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS),
        "runtime_design_required_contracts": sorted(set(runtime_design.required_contracts)),
        "default_contract_drafts": _default_contract_drafts(runtime_design),
        "contract_rules": {
            "contract_drafts": "Must include every required_agent_package_contract and every runtime_design_required_contract.",
            "capability_plans": "Must include every standard_capability_systems item, including disabled systems.",
            "pattern_slots": "Every Runtime Design pattern slot must be mapped to the right contract, resource requirement, generated tool, prompt, scheduler strategy, artifact strategy, or state strategy.",
            "builder_paths": "Never include Python import paths or builder paths. Builders are system registered.",
            "tool_execution": "All generated or builtin tools execute through ToolExecutionGateway.",
            "knowledge": "Knowledge retrieval is exposed as the system knowledge tool; no automatic full recall per turn.",
            "scheduler": "Scheduled script/tool execution uses scheduler runtime and ToolExecutionGateway.",
            "state": "State contract must match runtime_design state_namespaces and writable nodes.",
            "state_namespace_merge": "If Runtime Design declares multiple logical state namespaces, Capability Contract maps them into one physical state contract namespace and records the logical sections in capability_plans.state.what.",
            "resource_state_separation": "Runtime resources are the only source of runtime configuration values. Package state must not duplicate resource fields; it stores confirmations, progress, derived results, and other business state.",
            "sandbox_dependency_separation": "Sandbox services are external endpoints only. Python packages, system packages, and binaries belong exclusively in the dependencies contract.",
        },
    }


def validate_capability_contract(
    output: CapabilityContractOutput,
    *,
    runtime_design: RuntimeDesignOutput,
) -> CapabilityContractValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    contract_drafts = output.contract_drafts
    capability_plans = output.capability_plans

    missing_plans = sorted(set(STANDARD_CAPABILITY_SYSTEMS).difference(capability_plans))
    if missing_plans:
        errors.append("capability_plans missing systems: " + ", ".join(missing_plans))
    unknown_plans = sorted(set(capability_plans).difference(STANDARD_CAPABILITY_SYSTEMS))
    if unknown_plans:
        errors.append("capability_plans contains unknown systems: " + ", ".join(unknown_plans))

    required_contracts = set(REQUIRED_AGENT_PACKAGE_CONTRACTS).union(runtime_design.required_contracts)
    missing_contracts = sorted(required_contracts.difference(contract_drafts))
    if missing_contracts:
        errors.append("contract_drafts missing required contracts: " + ", ".join(missing_contracts))

    registry = default_runtime_contract_registry()
    enabled_contracts: list[str] = []
    disabled_contracts: list[str] = []
    for key, draft in sorted(contract_drafts.items()):
        if key != draft.type:
            errors.append(f"contract_drafts.{key} type mismatch: {draft.type}")
        try:
            registry.parse(draft.model_dump(mode="json"))
        except Exception as exc:
            errors.append(f"contract_drafts.{key} failed contract schema validation: {exc}")
        if draft.enabled:
            enabled_contracts.append(key)
        else:
            disabled_contracts.append(key)

    for required in sorted(set(runtime_design.required_contracts)):
        draft = contract_drafts.get(required)
        if draft is not None and not draft.enabled:
            errors.append(f"runtime design requires contract {required}, but draft is disabled")

    for key, plan in sorted(capability_plans.items()):
        draft = contract_drafts.get(key)
        if draft is not None and draft.enabled != plan.enabled:
            errors.append(f"{key} capability enabled={plan.enabled} conflicts with contract enabled={draft.enabled}")
        if plan.enabled and not plan.why.strip():
            errors.append(f"{key} capability plan must explain why it is enabled")
        if plan.enabled and not plan.strategy:
            errors.append(f"{key} capability plan must include strategy")

    _validate_runtime_design_alignment(output, runtime_design, errors, warnings)

    return CapabilityContractValidationReport(
        status="invalid" if errors else "valid",
        errors=errors,
        warnings=warnings,
        enabled_contracts=enabled_contracts,
        disabled_contracts=disabled_contracts,
        generation_task_summary={
            "tools": len(output.tool_specs_to_generate),
            "package_nodes": len(output.package_nodes_to_generate),
            "prompts": len(output.prompts_to_generate),
            "bindings": len(output.bindings_to_generate),
            "resources": len(output.resources_required),
            "sandbox_requirements": len(output.sandbox_requirements),
        },
    )


def capability_contract_message(
    output: CapabilityContractOutput,
    report: CapabilityContractValidationReport,
) -> str:
    lines = [
        "Capability Contract 已完成。",
        "",
        "已启用基础能力：",
        ", ".join(report.enabled_contracts) if report.enabled_contracts else "无",
    ]
    disabled = sorted(set(STANDARD_CAPABILITY_SYSTEMS).intersection(report.disabled_contracts))
    if disabled:
        lines.extend(["", "已关闭基础能力：", ", ".join(disabled)])
    lines.extend(["", "能力接入策略："])
    for key in STANDARD_CAPABILITY_SYSTEMS:
        plan = output.capability_plans.get(key)
        if plan is None:
            continue
        status = "启用" if plan.enabled else "关闭"
        lines.append(f"- {key}：{status}。{plan.why}")
    if output.tool_specs_to_generate:
        lines.extend(["", "后续需要生成的工具："])
        for item in output.tool_specs_to_generate:
            lines.append(f"- {item.tool_id}：{item.purpose}")
    if output.package_nodes_to_generate:
        lines.extend(["", "后续需要生成的 package-local node："])
        for item in output.package_nodes_to_generate:
            lines.append(f"- {item.impl_id}：{item.purpose}")
    if output.resources_required:
        lines.extend(["", "后续需要准备的资源："])
        for item in output.resources_required:
            required = "必需" if item.required else "可选"
            lines.append(f"- {item.resource_id}（{required}）：{item.description}")
    if output.sandbox_requirements:
        lines.extend(["", "Sandbox 运行要求："])
        for item in output.sandbox_requirements:
            lines.append(f"- {item.requirement_id}：{item.description}")
    if report.warnings:
        lines.extend(["", "校验提示：", *[f"- {item}" for item in report.warnings]])
    if output.capability_summary_text:
        lines.extend(["", "装配说明：", output.capability_summary_text])
    return "\n".join(lines).strip()


def validation_feedback_text(report: CapabilityContractValidationReport | None) -> str:
    if report is None:
        return "无。"
    if report.status == "valid":
        return "上一轮 Capability Contract 已通过 contract registry 与 Runtime Design 对齐校验。"
    lines = ["上一轮 Capability Contract 未通过校验，请修正以下问题："]
    lines.extend(f"- {item}" for item in report.errors)
    if report.warnings:
        lines.append("警告：")
        lines.extend(f"- {item}" for item in report.warnings)
    return "\n".join(lines)


def _validate_runtime_design_alignment(
    output: CapabilityContractOutput,
    runtime_design: RuntimeDesignOutput,
    errors: list[str],
    warnings: list[str],
) -> None:
    if runtime_design.state_namespaces:
        state_draft = output.contract_drafts.get("state")
        if state_draft is None or not state_draft.enabled:
            errors.append("runtime design declares state_namespaces but state contract is missing or disabled")
        elif len(runtime_design.state_namespaces) > 1:
            warnings.append(
                "Runtime Design declared multiple logical state namespaces; "
                "Capability Contract will materialize them as logical sections inside one physical state namespace."
            )
            state_plan = output.capability_plans.get("state")
            logical = []
            if state_plan is not None:
                raw = state_plan.what.get("logical_namespaces")
                if isinstance(raw, list):
                    logical = [str(item) for item in raw]
            expected = sorted(namespace.namespace for namespace in runtime_design.state_namespaces)
            missing = sorted(set(expected).difference(logical))
            if missing:
                errors.append(
                    "state capability plan must record merged logical_namespaces: "
                    + ", ".join(missing)
                )

    if runtime_design.package_nodes_to_generate:
        node_provider = output.contract_drafts.get("node_provider")
        if node_provider is None or not node_provider.enabled:
            errors.append("runtime design requires package-local nodes but node_provider contract is missing or disabled")
        expected = {item.impl_id for item in runtime_design.package_nodes_to_generate}
        actual = {item.impl_id for item in output.package_nodes_to_generate}
        missing = sorted(expected.difference(actual))
        if missing:
            errors.append("package_nodes_to_generate missing Runtime Design package nodes: " + ", ".join(missing))

    if runtime_design.structured_outputs:
        produced_by = {item.produced_by_node for item in runtime_design.structured_outputs}
        binding_nodes = {
            item.node_id
            for item in output.bindings_to_generate
            if item.binding_type == "model_operation"
        }
        missing = sorted(produced_by.difference(binding_nodes))
        if missing:
            errors.append("structured output nodes need model_operation bindings: " + ", ".join(missing))

    if any(node.requires_tools for node in runtime_design.nodes):
        draft = output.contract_drafts.get("tools")
        if draft is None or not draft.enabled:
            errors.append("Runtime Design has tool-using nodes but tools contract is missing or disabled")

    _validate_pattern_slot_alignment(output, runtime_design, errors)

    if output.resources_required:
        draft = output.contract_drafts.get("resources")
        if draft is None or not draft.enabled:
            errors.append("resources_required is non-empty but resources contract is missing or disabled")

    if output.sandbox_requirements:
        draft = output.contract_drafts.get("sandbox")
        if draft is None or not draft.enabled:
            errors.append("sandbox_requirements is non-empty but sandbox contract is missing or disabled")

    if "trace" not in output.contract_drafts or not output.contract_drafts["trace"].enabled:
        warnings.append("trace contract should stay enabled for manufactured AgentPackage diagnosis and upgrade")


def _validate_pattern_slot_alignment(
    output: CapabilityContractOutput,
    runtime_design: RuntimeDesignOutput,
    errors: list[str],
) -> None:
    generated_tools = {item.tool_id for item in output.tool_specs_to_generate}
    resources = {item.resource_id for item in output.resources_required}
    prompts = {item.prompt_id for item in output.prompts_to_generate}
    enabled_contracts = {
        key
        for key, draft in output.contract_drafts.items()
        if draft.enabled
    }
    for slot in runtime_design.pattern_slots:
        binding = slot.binding
        if slot.slot_type == "tool":
            if "tools" not in enabled_contracts:
                errors.append(f"pattern slot {slot.slot_id} requires tools contract")
            if slot.source == "package_generated":
                expected_tool_ids = list(getattr(binding, "generated_tool_ids", []) or getattr(binding, "tool_ids", []))
                if not expected_tool_ids:
                    errors.append(f"package_generated tool slot {slot.slot_id} must set tool_id")
                for tool_id in expected_tool_ids:
                    if tool_id not in generated_tools:
                        errors.append(f"tool slot {slot.slot_id} missing generated tool plan: {tool_id}")
        if slot.slot_type == "resource":
            if "resources" not in enabled_contracts:
                errors.append(f"pattern slot {slot.slot_id} requires resources contract")
            resource_id = str(getattr(binding, "resource_id", "") or "")
            if resource_id and resource_id not in resources:
                errors.append(f"resource slot {slot.slot_id} missing resource requirement: {resource_id}")
        if slot.slot_type == "prompt":
            prompt_id = str(getattr(binding, "prompt_id", "") or "")
            if prompt_id and prompt_id not in prompts:
                errors.append(f"prompt slot {slot.slot_id} missing prompt generation plan: {prompt_id}")
        if slot.slot_type == "scheduler" and "scheduler" not in enabled_contracts:
            errors.append(f"scheduler slot {slot.slot_id} requires scheduler contract")
        if slot.slot_type == "artifact" and "artifact" not in enabled_contracts:
            errors.append(f"artifact slot {slot.slot_id} requires artifact contract")
        if slot.slot_type == "state" and "state" not in enabled_contracts:
            errors.append(f"state slot {slot.slot_id} requires state contract")


def _default_contract_drafts(runtime_design: RuntimeDesignOutput) -> dict[str, dict[str, Any]]:
    state_namespace = _physical_state_namespace(runtime_design)
    writable_node_ids = sorted(
        {
            node.node_id
            for node in runtime_design.nodes
            if node.writes_state or node.requires_structured_output or node.requires_package_node
        }
    )
    state = default_state_contract().model_copy(
        update={
            "enabled": bool(runtime_design.state_namespaces),
            "config": StateContractConfig(
                namespace=state_namespace,
                schema_path=f"state/{state_namespace}.schema.json",
                initial_state_path=f"state/{state_namespace}.initial.json",
                writable_node_ids=writable_node_ids,
            ),
        },
        deep=True,
    )
    node_provider = default_node_provider_contract().model_copy(
        update={
            "enabled": bool(runtime_design.package_nodes_to_generate),
            "config": NodeProviderContractConfig(
                providers=[
                    NodeProviderReference(
                        provider_id="builtin.package_nodes",
                        config={"roots": ["nodes"]},
                    )
                ]
                if runtime_design.package_nodes_to_generate
                else []
            ),
        },
        deep=True,
    )
    drafts = {
        "artifact": default_artifact_contract(),
        "context": default_context_contract(),
        "dependencies": default_dependencies_contract(),
        "knowledge": default_knowledge_contract(),
        "memory": default_memory_contract(),
        "model": default_model_contract(),
        "node_provider": node_provider,
        "render": default_render_contract(),
        "resources": default_resources_contract(),
        "sandbox": default_sandbox_contract(),
        "scheduler": default_scheduler_contract(),
        "session": default_session_contract(),
        "state": state,
        "tools": default_tools_contract(),
        "trace": default_trace_contract(),
    }
    return {key: value.model_dump(mode="json") for key, value in drafts.items()}


def _physical_state_namespace(runtime_design: RuntimeDesignOutput) -> str:
    if not runtime_design.state_namespaces:
        return "package"
    if len(runtime_design.state_namespaces) == 1:
        return runtime_design.state_namespaces[0].namespace
    return "agent_state"
