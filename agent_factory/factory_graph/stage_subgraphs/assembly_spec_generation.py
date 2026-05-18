from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from langgraph.graph import END, START, StateGraph

from agent_factory.assembly.schema import AgentAssemblySpec, ToolSpec
from agent_factory.assembly.validator import AgentAssemblyValidationError, AgentAssemblyValidator
from agent_factory.runtime_kernel.bindings import (
    CustomBindingPayload,
    OutputFormatterBindingPayload,
    PolicyProfileBindingPayload,
    PromptBindingPayload,
    StrategyProfileBindingPayload,
    ToolAccessBindingPayload,
)
from agent_factory.factory_graph.model_call import FactoryModelCallError, call_structured_model
from agent_factory.factory_graph.schemas import (
    AssemblyReactDecision,
    AssemblyValidationAttempt,
    AssemblyValidationReport,
    PackageMaterializationFileSpec,
    PackageMaterializationPlan,
    PackageMaterializationToolSpec,
    PackageMaterializationValidationReport,
)
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.prompts import PromptId, output_json_schema
from agent_factory.runtime_render import NodeRenderSpec, RenderManifest, validate_render_manifest
from agent_factory.runtime_kernel.patterns import PatternRegistry
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskLevel


ASSEMBLY_VALIDATION_VERSION = "assembly_validation.v0"
ASSEMBLY_ROOT = ".agentfactory/assemblies"
MAX_REVISION_ROUNDS = 3
STAGE_ID = "assembly_spec_generation"


def build_assembly_spec_generation_subgraph():
    graph = StateGraph(FactoryGraphState)
    graph.add_node("initialize_assembly_context", _initialize_assembly_context)
    graph.add_node("assembly_react_model", _assembly_react_model)
    graph.add_node("validate_assembly_draft", _validate_assembly_draft)
    graph.add_node("publish_assembly_spec_draft", _publish_assembly_spec_draft)
    graph.add_node("fail_assembly_generation", _fail_assembly_generation)
    graph.add_edge(START, "initialize_assembly_context")
    graph.add_edge("initialize_assembly_context", "assembly_react_model")
    graph.add_conditional_edges(
        "assembly_react_model",
        _route_after_model,
        {
            "validate_assembly_draft": "validate_assembly_draft",
            "fail_assembly_generation": "fail_assembly_generation",
        },
    )
    graph.add_conditional_edges(
        "validate_assembly_draft",
        _route_after_validation,
        {
            "publish_assembly_spec_draft": "publish_assembly_spec_draft",
            "assembly_react_model": "assembly_react_model",
            "fail_assembly_generation": "fail_assembly_generation",
        },
    )
    graph.add_edge("publish_assembly_spec_draft", END)
    graph.add_edge("fail_assembly_generation", END)
    return graph.compile()


def run_assembly_spec_generation_subgraph(state: FactoryGraphState) -> dict[str, Any]:
    return build_assembly_spec_generation_subgraph().invoke(state)


def _initialize_assembly_context(state: FactoryGraphState) -> dict[str, Any]:
    factory_run_id = str(state.get("factory_run_id") or "")
    paths = _assembly_paths(factory_run_id)
    return {
        "current_stage": STAGE_ID,
        "assembly_validation_report": AssemblyValidationReport(status="invalid").model_dump(mode="json"),
        "assembly_spec_draft_path": str(paths["draft"]),
        "package_materialization_plan_path": str(paths["plan"]),
        "assembly_validation_report_path": str(paths["report"]),
    }


def _assembly_react_model(state: FactoryGraphState) -> dict[str, Any]:
    attempt = _attempt_count(state) + 1
    try:
        decision = call_structured_model(
            stage_id=STAGE_ID,
            prompt_id=PromptId.ASSEMBLY_SPEC_REACT,
            output_model=AssemblyReactDecision,
            values={
                "requirement_brief": _json_text(state.get("requirement_brief") or {}),
                "refined_plan_text": state.get("refined_plan_text") or "",
                "runtime_pattern_selection": _json_text(state.get("runtime_pattern_selection") or {}),
                "pattern_structure_summary": _json_text(state.get("pattern_structure_summary") or {}),
                "graph_behavior_plan": _json_text(state.get("graph_behavior_plan") or {}),
                "node_strategy_plan": _json_text(state.get("node_strategy_plan") or {}),
                "tool_capability_plan": _json_text(state.get("tool_capability_plan") or {}),
                "resource_condition_plan": _json_text(state.get("resource_condition_plan") or {}),
                "previous_draft": _json_text(state.get("assembly_spec_draft_candidate") or {}),
                "validation_observation": _json_text(state.get("assembly_validation_observation") or {}),
                "output_json_schema": output_json_schema(AssemblyReactDecision),
            },
        )
    except FactoryModelCallError as exc:
        return _failed_patch(f"assembly react model failed: {exc}", attempt=attempt)
    if decision.action != "draft_ready":
        return _failed_patch(decision.blocked_reason or f"assembly react decision: {decision.action}", attempt=attempt)
    if decision.draft is None:
        return _failed_patch("assembly react decision did not include draft", attempt=attempt)
    return {
        "assembly_react_attempt": attempt,
        "assembly_react_decision": decision.model_dump(mode="json"),
        "assembly_spec_draft_candidate": decision.draft.model_dump(mode="json"),
    }


def _validate_assembly_draft(state: FactoryGraphState) -> dict[str, Any]:
    attempt = int(state.get("assembly_react_attempt") or _attempt_count(state) + 1)
    candidate = dict(state.get("assembly_spec_draft_candidate") or {})
    errors: list[str] = []
    normalized_spec: dict[str, Any] | None = None
    try:
        spec = _with_system_runtime_contract(_candidate_to_spec(candidate), state)
        errors.extend(_stage_constraint_errors(spec, state))
        if not errors:
            validator = AgentAssemblyValidator(pattern_registry=_pattern_registry())
            validated_spec = validator.validate(spec)
            normalized_spec = validated_spec.model_dump(mode="json")
    except (ValidationError, AgentAssemblyValidationError, Exception) as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    status = "valid" if not errors and normalized_spec is not None else "invalid"
    attempt_record = AssemblyValidationAttempt(attempt=attempt, status=status, errors=errors)
    report = _updated_report(state, attempt_record)
    observation = {
        "attempt": attempt,
        "status": status,
        "errors": errors,
        "allowed_fix_scope": "Only modify assembly draft. Do not modify upstream plans.",
    }
    return {
        "assembly_validation_observation": observation,
        "assembly_validation_report": report.model_dump(mode="json"),
        **({"assembly_spec_draft": normalized_spec, "assembly_spec": normalized_spec} if normalized_spec else {}),
    }


def _publish_assembly_spec_draft(state: FactoryGraphState) -> dict[str, Any]:
    spec = dict(state.get("assembly_spec_draft") or {})
    report = dict(state.get("assembly_validation_report") or {})
    factory_run_id = str(state.get("factory_run_id") or "")
    paths = _assembly_paths(factory_run_id)
    spec_model = AgentAssemblySpec.model_validate(spec)
    render_manifest = _build_render_manifest(spec_model, state)
    render_report_errors = _validate_render_manifest_for_stage(render_manifest, spec_model)
    if render_report_errors:
        failed = AssemblyValidationReport(
            status="failed",
            attempts=[
                *[
                    AssemblyValidationAttempt.model_validate(item)
                    for item in report.get("attempts", []) or []
                ],
                AssemblyValidationAttempt(
                    attempt=_attempt_count(state) + 1,
                    status="invalid",
                    errors=render_report_errors,
                ),
            ],
            final_error="; ".join(render_report_errors),
        )
        return _fail_assembly_generation({**state, "assembly_validation_report": failed.model_dump(mode="json")})
    metadata = dict(spec_model.metadata or {})
    metadata.update(
        {
            "render_manifest_version": render_manifest.version,
            "render_manifest_path": str(paths["render_manifest"]),
            "render_node_ids": sorted(render_manifest.nodes),
            "render_manifest": render_manifest.model_dump(mode="json"),
        }
    )
    spec_model = spec_model.model_copy(update={"metadata": metadata}, deep=True)
    spec = spec_model.model_dump(mode="json")
    materialization_plan = _build_package_materialization_plan(
        spec_model,
        state,
    )
    plan_report = _validate_materialization_plan(materialization_plan, state)
    if plan_report.status != "valid":
        failed = AssemblyValidationReport(
            status="failed",
            attempts=[
                *[
                    AssemblyValidationAttempt.model_validate(item)
                    for item in report.get("attempts", []) or []
                ],
                AssemblyValidationAttempt(
                    attempt=_attempt_count(state) + 1,
                    status="invalid",
                    errors=plan_report.errors,
                ),
            ],
            final_error="; ".join(plan_report.errors),
        )
        return _fail_assembly_generation({**state, "assembly_validation_report": failed.model_dump(mode="json")})
    paths["draft"].parent.mkdir(parents=True, exist_ok=True)
    paths["draft"].write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["spec"].write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["render_manifest"].write_text(json.dumps(render_manifest.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    paths["plan"].write_text(json.dumps(materialization_plan.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    paths["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "current_stage": STAGE_ID,
        "status": "running",
        "assembly_spec_draft": spec,
        "assembly_spec": spec,
        "package_materialization_plan": materialization_plan.model_dump(mode="json"),
        "render_manifest": render_manifest.model_dump(mode="json"),
        "render_manifest_path": str(paths["render_manifest"]),
        "assembly_validation_report": report,
        "assembly_spec_draft_path": str(paths["draft"]),
        "package_materialization_plan_path": str(paths["plan"]),
        "assembly_validation_report_path": str(paths["report"]),
        "stage_log": [
            {
                "stage_id": STAGE_ID,
                "status": "generated",
                "message": "assembly_spec_generation froze assembly spec and package materialization plan.",
            }
        ],
    }


def _fail_assembly_generation(state: FactoryGraphState) -> dict[str, Any]:
    report = _failed_report(state)
    factory_run_id = str(state.get("factory_run_id") or "")
    paths = _assembly_paths(factory_run_id)
    paths["report"].parent.mkdir(parents=True, exist_ok=True)
    paths["report"].write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    message = report.final_error or "assembly spec generation failed"
    return {
        "current_stage": STAGE_ID,
        "status": "failed",
        "graph_control": {"action": "end"},
        "assembly_validation_report": report.model_dump(mode="json"),
        "assembly_validation_report_path": str(paths["report"]),
        "errors": [{"where": STAGE_ID, "attempt": str(_attempt_count(state)), "message": message}],
        "stage_log": [{"stage_id": STAGE_ID, "status": "failed", "message": message}],
    }


def _route_after_model(state: FactoryGraphState) -> str:
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return "fail_assembly_generation"
    return "validate_assembly_draft"


def _route_after_validation(state: FactoryGraphState) -> str:
    observation = dict(state.get("assembly_validation_observation") or {})
    if observation.get("status") == "valid":
        return "publish_assembly_spec_draft"
    if _attempt_count(state) >= MAX_REVISION_ROUNDS:
        return "fail_assembly_generation"
    return "assembly_react_model"


def _candidate_to_spec(candidate: dict[str, Any]) -> AgentAssemblySpec:
    return AgentAssemblySpec(
        agent=candidate.get("agent") or {},
        runtime=candidate.get("runtime") or {},
        graph_overrides=candidate.get("graph_overrides") or {},
        bindings=candidate.get("bindings") or {},
        tools=candidate.get("tools") or [],
        output=candidate.get("output") or {},
        metadata=candidate.get("metadata") or {},
    )


def _stage_constraint_errors(spec: AgentAssemblySpec, state: FactoryGraphState) -> list[str]:
    errors: list[str] = []
    selected_pattern_id = str(dict(state.get("runtime_pattern_selection") or {}).get("selected_pattern_id") or "")
    if spec.runtime.pattern_id != selected_pattern_id:
        errors.append(f"runtime.pattern_id must be selected pattern_id: {selected_pattern_id}")
    node_ids = _graph_node_ids(state)
    for override in spec.graph_overrides.node_wrappers:
        if override.node_id not in node_ids:
            errors.append(f"graph_overrides.node_wrappers references upstream-unknown node_id: {override.node_id}")
    capability_ids = _tool_capability_ids(state)
    for tool in spec.tools:
        if tool.id not in capability_ids:
            errors.append(f"tools[].id must come from tool_capability_plan: {tool.id}")
    errors.extend(_binding_contract_errors(spec, state))
    metadata = dict(spec.metadata or {})
    required_metadata = {
        "factory_run_id": str(state.get("factory_run_id") or ""),
        "resource_file_path": _resource_file_path(state),
        "sandbox_contract_path": _sandbox_contract_path(state),
        "resource_preparation_report_path": _resource_preparation_report_path(state),
        "session_config_path": "session.json",
        "memory_store_config_path": "memory/store.json",
        "source_stage_ids": [
            "requirement_capture",
            "runtime_pattern_selection",
            "graph_behavior_planning",
            "node_strategy_planning",
            "tool_capability_planning",
            "resource_and_condition_planning",
        ],
        "tool_capability_ids": sorted(capability_ids),
    }
    for key, expected in required_metadata.items():
        if metadata.get(key) != expected:
            errors.append(f"metadata.{key} must equal {expected!r}")
    if spec.harness:
        errors.append("harness must be empty in stage 7")
    return errors


def _with_system_runtime_contract(spec: AgentAssemblySpec, state: FactoryGraphState) -> AgentAssemblySpec:
    runtime = spec.runtime.model_copy(
        update={
            "session_config": {
                **_default_agent_session_config(),
                **dict(spec.runtime.session_config or {}),
            }
        },
        deep=True,
    )
    metadata = {
        **dict(spec.metadata or {}),
        "factory_run_id": str(state.get("factory_run_id") or ""),
        "resource_file_path": _resource_file_path(state),
        "sandbox_contract_path": _sandbox_contract_path(state),
        "resource_preparation_report_path": _resource_preparation_report_path(state),
        "session_config_path": "session.json",
        "memory_store_config_path": "memory/store.json",
        "memory_store": _default_agent_memory_store_config(),
    }
    return spec.model_copy(update={"runtime": runtime, "metadata": metadata}, deep=True)


def _default_agent_session_config() -> dict[str, str]:
    return {
        "session_root": ".agent_runtime/sessions",
        "checkpointer_backend": "sqlite",
        "checkpoint_path": ".agent_runtime/checkpoints/agent.sqlite",
    }


def _default_agent_memory_store_config() -> dict[str, str]:
    return {
        "backend": "sqlite",
        "path": ".agent_runtime/memory/agent.sqlite",
    }


def _binding_contract_errors(spec: AgentAssemblySpec, state: FactoryGraphState) -> list[str]:
    errors: list[str] = []
    pattern_nodes = _pattern_nodes(spec.runtime.pattern_id)
    node_ids = set(pattern_nodes)
    bindings = spec.bindings
    if not bindings.node_bindings:
        return ["bindings.node_bindings must define node-level assembly contracts"]
    if not bindings.services:
        errors.append("bindings.services must declare runtime service contracts")
    for binding in bindings.node_bindings:
        target = binding.target
        if target.node_id not in node_ids:
            errors.append(f"bindings.node_bindings target unknown node_id: {target.node_id}")
            continue
        expected_impl = pattern_nodes[target.node_id]["impl"]
        if target.impl != expected_impl:
            errors.append(f"bindings.node_bindings target impl mismatch for {target.node_id}: expected {expected_impl}")
        errors.extend(_binding_payload_errors(binding.binding_type, _payload_dict(binding.payload), binding.target.node_id))
    required_by_node = _required_binding_types_by_node(pattern_nodes, state)
    bindings_by_node: dict[str, set[str]] = {}
    for binding in bindings.node_bindings:
        bindings_by_node.setdefault(binding.target.node_id, set()).add(binding.binding_type)
    for node_id, required_types in required_by_node.items():
        missing = sorted(required_types - bindings_by_node.get(node_id, set()))
        if missing:
            errors.append(f"bindings.node_bindings missing {missing} for node_id: {node_id}")
    tool_ids = {tool.id for tool in spec.tools}
    tool_access_ids = set()
    for binding in bindings.node_bindings:
        if binding.binding_type != "tool_access":
            continue
        payload = _payload_dict(binding.payload)
        allowed = payload.get("allowed_tool_ids") or []
        if not isinstance(allowed, list):
            continue
        tool_access_ids.update(str(item) for item in allowed)
    missing_tool_access = sorted(tool_ids - tool_access_ids)
    if missing_tool_access:
        errors.append(f"bindings.node_bindings tool_access must expose tools: {missing_tool_access}")
    service_kinds = {service.kind for service in bindings.services}
    for required_kind in _required_service_kinds(spec, pattern_nodes):
        if required_kind not in service_kinds:
            errors.append(f"bindings.services missing required service kind: {required_kind}")
    return errors


def _binding_payload_errors(binding_type: str, payload: dict[str, Any], node_id: str) -> list[str]:
    payload_model_by_type = {
        "prompt": PromptBindingPayload,
        "tool_access": ToolAccessBindingPayload,
        "policy_profile": PolicyProfileBindingPayload,
        "strategy_profile": StrategyProfileBindingPayload,
        "output_formatter": OutputFormatterBindingPayload,
        "custom": CustomBindingPayload,
    }
    payload_model = payload_model_by_type.get(binding_type)
    if payload_model is None:
        return []
    try:
        payload_model.model_validate(payload)
    except Exception as exc:
        return [f"bindings.node_bindings invalid {binding_type} payload for {node_id}: {type(exc).__name__}: {exc}"]
    return []


def _payload_dict(payload: Any) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(mode="json")
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _required_binding_types_by_node(pattern_nodes: dict[str, dict[str, str]], state: FactoryGraphState) -> dict[str, set[str]]:
    required: dict[str, set[str]] = {}
    for node_id, node in pattern_nodes.items():
        impl = node["impl"]
        node_type = node["type"]
        if impl.startswith("cognitive."):
            required.setdefault(node_id, set()).add("prompt")
        if impl == "operational.tool_call":
            required.setdefault(node_id, set()).add("tool_access")
        if impl.startswith("governance."):
            required.setdefault(node_id, set()).add("policy_profile")
        if node_type == "terminal" or impl == "finalize":
            required.setdefault(node_id, set()).add("output_formatter")
    for node_id in _nodes_with_strategy_refs(state):
        if node_id in pattern_nodes:
            required.setdefault(node_id, set()).add("strategy_profile")
    return required


def _nodes_with_strategy_refs(state: FactoryGraphState) -> set[str]:
    plan = dict(state.get("node_strategy_plan") or {})
    nodes: set[str] = set()
    for item in plan.get("node_strategies", []) or []:
        if item.get("strategy_refs"):
            nodes.add(str(item.get("node_id") or ""))
    return nodes


def _required_service_kinds(spec: AgentAssemblySpec, pattern_nodes: dict[str, dict[str, str]]) -> set[str]:
    required: set[str] = {"observability_manager", "checkpointer", "memory_store"}
    if any(node["impl"].startswith("cognitive.") for node in pattern_nodes.values()):
        required.add("model_service")
        required.add("context_engine")
    if spec.tools or any(binding.binding_type == "tool_access" for binding in spec.bindings.node_bindings):
        required.add("tool_registry")
    if any(node["impl"].startswith("operational.knowledge") for node in pattern_nodes.values()):
        required.add("knowledge_engine")
    if any(node["impl"].startswith("governance.") for node in pattern_nodes.values()):
        required.add("policy_engine")
    return required


def _build_package_materialization_plan(spec: AgentAssemblySpec, state: FactoryGraphState) -> PackageMaterializationPlan:
    factory_run_id = str(state.get("factory_run_id") or "default")
    package_root = f".agentfactory/packages/{factory_run_id}"
    files: list[PackageMaterializationFileSpec] = [
        _file_spec("agent_package.json", "json", "manifest", "agent_package", "system_generated", "assembly_spec+package_materialization_plan"),
        _file_spec("assembly_spec.json", "json", "assembly", "assembly_spec", "system_generated", "assembly_spec"),
        _file_spec("resources.json", "json", "manifest", "resources", "system_generated", "resource_condition_plan.resources"),
        _file_spec("sandbox_contract.json", "json", "manifest", "sandbox_contract", "system_generated", "resource_condition_plan.sandbox_contract"),
        _file_spec("render_manifest.json", "json", "manifest", "render_manifest", "system_generated", "assembly_spec.metadata.render_manifest"),
        _file_spec("package_report.json", "json", "manifest", "package_report", "system_generated", "package_validation_report"),
        _file_spec("bindings/services.json", "json", "binding", "services", "system_generated", "assembly_spec.bindings.services"),
        _file_spec("bindings/node_bindings.json", "json", "binding", "node_bindings", "system_generated", "assembly_spec.bindings.node_bindings"),
        _file_spec("bindings/hooks.json", "json", "binding", "hooks", "system_generated", "assembly_spec.bindings.hooks"),
        _file_spec("session.json", "json", "manifest", "session", "system_generated", "assembly_spec.runtime.session_config"),
        _file_spec("memory/store.json", "json", "manifest", "memory_store", "system_generated", "assembly_spec.metadata.memory_store"),
    ]
    tool_capabilities = _tool_capabilities_by_id(state)
    tool_specs: list[PackageMaterializationToolSpec] = []
    for binding in spec.bindings.node_bindings:
        payload = _payload_dict(binding.payload)
        if binding.binding_type == "prompt":
            prompt_id = str(payload.get("prompt_id") or binding.binding_id)
            generation_mode = "system_generated" if payload.get("template") else "model_generated"
            files.append(_file_spec(f"prompts/{prompt_id}.md", "markdown", "prompt", prompt_id, generation_mode, f"binding:{binding.binding_id}"))
        elif binding.binding_type == "policy_profile":
            profile_id = str(payload.get("profile_id") or binding.binding_id)
            files.append(_file_spec(f"policies/{profile_id}.json", "json", "policy", profile_id, "system_generated", f"binding:{binding.binding_id}"))
        elif binding.binding_type == "strategy_profile":
            files.append(_file_spec(f"strategies/{binding.target.node_id}.json", "json", "strategy", binding.target.node_id, "system_generated", f"binding:{binding.binding_id}"))
        elif binding.binding_type == "output_formatter":
            formatter_id = str(payload.get("formatter_id") or binding.binding_id)
            files.append(_file_spec(f"formatters/{formatter_id}.json", "json", "formatter", formatter_id, "system_generated", f"binding:{binding.binding_id}"))
    for tool in spec.tools:
        capability = tool_capabilities.get(tool.id, {})
        manifest = ToolSpec(
            id=tool.id,
            description=tool.description or str(capability.get("description") or tool.id),
            entrypoint=f"tools/{tool.id}/tool.py:run",
            input_schema=dict(capability.get("input_contract") or tool.input_schema or {"type": "object"}),
            output_schema=dict(capability.get("output_contract") or tool.output_schema or {"type": "object"}),
            resources={resource_key: resource_key for resource_key in _resource_keys_for_tool(tool.id, state)},
            risk_level=_risk_level_from_capability(capability),
            risk_evaluator=ToolRiskEvaluatorConfig(hard=f"tools/{tool.id}/tool.py:evaluate_risk"),
            concurrent=bool(capability.get("concurrent", tool.concurrent)),
        )
        tool_specs.append(
            PackageMaterializationToolSpec(
                tool_id=tool.id,
                manifest_path=f"tools/{tool.id}/manifest.json",
                code_path=f"tools/{tool.id}/tool.py",
                readme_path=f"tools/{tool.id}/README.md",
                manifest=manifest,
            )
        )
        files.extend(
            [
                _file_spec(f"tools/{tool.id}/manifest.json", "json", "tool", tool.id, "system_generated", f"tool_capability:{tool.id}"),
                _file_spec(f"tools/{tool.id}/tool.py", "python", "tool", tool.id, "model_generated", f"tool_capability:{tool.id}+resources"),
                _file_spec(f"tools/{tool.id}/README.md", "markdown", "tool", tool.id, "model_generated", f"tool_capability:{tool.id}+resources"),
            ]
        )
    manifest_contract = {
        "version": "agent_package.v0",
        "factory_run_id": factory_run_id,
        "agent": spec.agent.model_dump(mode="json"),
        "runtime": spec.runtime.model_dump(mode="json"),
        "assembly_spec_path": "assembly_spec.json",
        "resources_path": "resources.json",
        "sandbox_contract_path": "sandbox_contract.json",
        "render_manifest_path": "render_manifest.json",
        "bindings": {
            "services": "bindings/services.json",
            "node_bindings": "bindings/node_bindings.json",
            "hooks": "bindings/hooks.json",
        },
        "session_path": "session.json",
        "memory_store_path": "memory/store.json",
        "prompts": sorted(item.path for item in files if item.source_kind == "prompt"),
        "tools": sorted(item.manifest_path for item in tool_specs),
        "policies": sorted(item.path for item in files if item.source_kind == "policy"),
        "strategy_profiles": sorted(item.path for item in files if item.source_kind == "strategy"),
        "formatters": sorted(item.path for item in files if item.source_kind == "formatter"),
    }
    return PackageMaterializationPlan(
        factory_run_id=factory_run_id,
        package_root=package_root,
        files=_dedupe_file_specs(files),
        tools=tool_specs,
        manifest_contract=manifest_contract,
    )


def _risk_level_from_capability(capability: dict[str, object]) -> ToolRiskLevel:
    if bool(capability.get("approval_required") or False):
        return "high"
    return "medium"


def _build_render_manifest(spec: AgentAssemblySpec, state: FactoryGraphState) -> RenderManifest:
    pattern_nodes = _pattern_nodes(spec.runtime.pattern_id)
    graph_nodes = _graph_behavior_nodes_by_id(state)
    strategy_nodes = _node_strategies_by_id(state)
    nodes: dict[str, NodeRenderSpec] = {}
    for node_id, pattern_node in pattern_nodes.items():
        graph_node = graph_nodes.get(node_id, {})
        strategy_node = strategy_nodes.get(node_id, {})
        node_type = str(graph_node.get("node_type") or strategy_node.get("node_type") or pattern_node.get("type") or "node")
        business_behavior = str(graph_node.get("business_behavior") or strategy_node.get("business_behavior_ref") or "")
        input_expectation = str(graph_node.get("input_expectation") or "")
        output_expectation = str(graph_node.get("output_expectation") or "")
        purpose = business_behavior or f"执行 {node_id} 节点职责。"
        doing = input_expectation or purpose
        expected_output = output_expectation or f"{node_id} 节点完成后的状态更新。"
        nodes[node_id] = NodeRenderSpec(
            node_id=node_id,
            label=_render_label(node_id),
            kind=node_type,
            purpose=purpose,
            doing=doing,
            expected_output=expected_output,
            visible_to_user=bool(graph_node.get("user_visible", True)),
        )
    return RenderManifest(
        graph_id=spec.runtime.compiled_pattern_id or f"{spec.agent.id}__{spec.runtime.pattern_id}",
        nodes=nodes,
    )


def _validate_render_manifest_for_stage(render_manifest: RenderManifest, spec: AgentAssemblySpec) -> list[str]:
    try:
        validate_render_manifest(render_manifest, set(_pattern_nodes(spec.runtime.pattern_id)))
    except Exception as exc:
        return [f"render_manifest invalid: {type(exc).__name__}: {exc}"]
    return []


def _validate_materialization_plan(plan: PackageMaterializationPlan, state: FactoryGraphState) -> PackageMaterializationValidationReport:
    errors: list[str] = []
    paths = {item.path for item in plan.files}
    required = {
        "agent_package.json",
        "assembly_spec.json",
        "resources.json",
        "bindings/services.json",
        "bindings/node_bindings.json",
        "bindings/hooks.json",
        "render_manifest.json",
        "sandbox_contract.json",
        "session.json",
        "memory/store.json",
    }
    for path in sorted(required - paths):
        errors.append(f"package_materialization_plan missing required binding file: {path}")
    tool_ids = _tool_capability_ids(state)
    for tool in plan.tools:
        if tool.tool_id not in tool_ids:
            errors.append(f"package_materialization_plan tool not in tool_capability_plan: {tool.tool_id}")
        capability = _tool_capabilities_by_id(state).get(tool.tool_id, {})
        if tool.manifest.input_schema != dict(capability.get("input_contract") or {}):
            errors.append(f"package_materialization_plan tool input contract mismatch: {tool.tool_id}")
        if tool.manifest.output_schema != dict(capability.get("output_contract") or {}):
            errors.append(f"package_materialization_plan tool output contract mismatch: {tool.tool_id}")
    forbidden = [item.path for item in plan.files if "harness" in item.path or "test_result" in item.path]
    for path in forbidden:
        errors.append(f"package_materialization_plan cannot include harness or dynamic test output: {path}")
    return PackageMaterializationValidationReport(status="invalid" if errors else "valid", errors=errors)


def _file_spec(
    path: str,
    file_type: str,
    source_kind: str,
    source_id: str,
    generation_mode: str,
    contract_source: str,
) -> PackageMaterializationFileSpec:
    return PackageMaterializationFileSpec(
        path=path,
        file_type=file_type,
        source_kind=source_kind,
        source_id=source_id,
        generation_mode=generation_mode,
        contract_source=contract_source,
    )


def _dedupe_file_specs(files: list[PackageMaterializationFileSpec]) -> list[PackageMaterializationFileSpec]:
    result: dict[str, PackageMaterializationFileSpec] = {}
    for item in files:
        result.setdefault(item.path, item)
    return list(result.values())


def _tool_capabilities_by_id(state: FactoryGraphState) -> dict[str, dict[str, Any]]:
    tool_plan = dict(state.get("tool_capability_plan") or {})
    return {
        str(item.get("capability_id") or ""): dict(item)
        for item in tool_plan.get("tool_capabilities", []) or []
        if item.get("capability_id")
    }


def _resource_keys_for_tool(tool_id: str, state: FactoryGraphState) -> list[str]:
    resource_plan = dict(state.get("resource_condition_plan") or {})
    keys: set[str] = set()
    for requirement in resource_plan.get("requirements", []) or []:
        if tool_id in (requirement.get("used_by_capability_ids") or []):
            keys.add(str(requirement.get("requirement_id") or ""))
    for key in dict(resource_plan.get("resources") or {}):
        if key == tool_id or key.startswith(f"{tool_id}_"):
            keys.add(str(key))
    return sorted(key for key in keys if key)


def _pattern_nodes(pattern_id: str) -> dict[str, dict[str, str]]:
    pattern = _pattern_registry().get(pattern_id)
    return {
        node.id: {
            "type": node.type,
            "impl": node.impl,
        }
        for node in pattern.nodes
    }


def _updated_report(state: FactoryGraphState, attempt: AssemblyValidationAttempt) -> AssemblyValidationReport:
    existing = dict(state.get("assembly_validation_report") or {})
    attempts = [AssemblyValidationAttempt.model_validate(item) for item in existing.get("attempts", []) or []]
    attempts.append(attempt)
    return AssemblyValidationReport(
        status="valid" if attempt.status == "valid" else "invalid",
        attempts=attempts,
        final_error="; ".join(attempt.errors) if attempt.errors else "",
    )


def _failed_report(state: FactoryGraphState) -> AssemblyValidationReport:
    existing = dict(state.get("assembly_validation_report") or {})
    attempts = [AssemblyValidationAttempt.model_validate(item) for item in existing.get("attempts", []) or []]
    final_error = str(existing.get("final_error") or "")
    if not final_error:
        observation = dict(state.get("assembly_validation_observation") or {})
        final_error = "; ".join(str(item) for item in observation.get("errors", []) or []) or "assembly generation failed"
    return AssemblyValidationReport(status="failed", attempts=attempts, final_error=final_error)


def _failed_patch(message: str, *, attempt: int) -> dict[str, Any]:
    report = AssemblyValidationReport(
        status="failed",
        attempts=[AssemblyValidationAttempt(attempt=attempt, status="invalid", errors=[message])],
        final_error=message,
    )
    return {
        "status": "failed",
        "graph_control": {"action": "end"},
        "assembly_validation_report": report.model_dump(mode="json"),
        "assembly_validation_observation": {"attempt": attempt, "status": "invalid", "errors": [message]},
    }


def _attempt_count(state: FactoryGraphState) -> int:
    report = dict(state.get("assembly_validation_report") or {})
    return len(report.get("attempts", []) or [])


def _assembly_paths(factory_run_id: str) -> dict[str, Path]:
    root = Path(ASSEMBLY_ROOT) / factory_run_id
    return {
        "draft": root / "assembly_spec_draft.json",
        "spec": root / "assembly_spec.json",
        "render_manifest": root / "render_manifest.json",
        "plan": root / "package_materialization_plan.json",
        "report": root / "assembly_validation_report.json",
    }


def _pattern_registry() -> PatternRegistry:
    builtins_dir = Path(__file__).resolve().parents[2] / "runtime_kernel" / "patterns" / "builtins"
    return PatternRegistry(builtins_dir=builtins_dir)


def _graph_node_ids(state: FactoryGraphState) -> set[str]:
    graph_behavior = dict(state.get("graph_behavior_plan") or {})
    return {str(item.get("node_id") or "") for item in graph_behavior.get("nodes", []) or []}


def _graph_behavior_nodes_by_id(state: FactoryGraphState) -> dict[str, dict[str, Any]]:
    graph_behavior = dict(state.get("graph_behavior_plan") or {})
    return {
        str(item.get("node_id") or ""): dict(item)
        for item in graph_behavior.get("nodes", []) or []
        if isinstance(item, dict) and item.get("node_id")
    }


def _node_strategies_by_id(state: FactoryGraphState) -> dict[str, dict[str, Any]]:
    strategy_plan = dict(state.get("node_strategy_plan") or {})
    return {
        str(item.get("node_id") or ""): dict(item)
        for item in strategy_plan.get("node_strategies", []) or []
        if isinstance(item, dict) and item.get("node_id")
    }


def _render_label(node_id: str) -> str:
    return node_id.replace("_", " ").title()


def _tool_capability_ids(state: FactoryGraphState) -> set[str]:
    tool_plan = dict(state.get("tool_capability_plan") or {})
    return {str(item.get("capability_id") or "") for item in tool_plan.get("tool_capabilities", []) or []}


def _resource_file_path(state: FactoryGraphState) -> str:
    plan = dict(state.get("resource_condition_plan") or {})
    return str(plan.get("resource_file_path") or "")


def _sandbox_contract_path(state: FactoryGraphState) -> str:
    plan = dict(state.get("resource_condition_plan") or {})
    return str(plan.get("sandbox_contract_path") or state.get("sandbox_contract_path") or "")


def _resource_preparation_report_path(state: FactoryGraphState) -> str:
    plan = dict(state.get("resource_condition_plan") or {})
    return str(plan.get("report_path") or state.get("resource_preparation_report_path") or "")


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
