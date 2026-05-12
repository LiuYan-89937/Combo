from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from langgraph.graph import END, START, StateGraph

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.assembly.validator import AgentAssemblyValidationError, AgentAssemblyValidator
from agent_factory.factory_graph.model_call import FactoryModelCallError, call_structured_model
from agent_factory.factory_graph.schemas import (
    AssemblyReactDecision,
    AssemblyValidationAttempt,
    AssemblyValidationReport,
)
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.prompts import PromptId, output_json_schema
from agent_factory.runtime_kernel.patterns import PatternRegistry


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
        spec = _candidate_to_spec(candidate)
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
    paths["draft"].parent.mkdir(parents=True, exist_ok=True)
    paths["draft"].write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "current_stage": STAGE_ID,
        "status": "running",
        "assembly_spec_draft": spec,
        "assembly_spec": spec,
        "assembly_validation_report": report,
        "assembly_spec_draft_path": str(paths["draft"]),
        "assembly_validation_report_path": str(paths["report"]),
        "stage_log": [
            {
                "stage_id": STAGE_ID,
                "status": "generated",
                "message": "assembly_spec_generation generated and validated assembly spec draft.",
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
    metadata = dict(spec.metadata or {})
    required_metadata = {
        "factory_run_id": str(state.get("factory_run_id") or ""),
        "resource_file_path": _resource_file_path(state),
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
        "report": root / "assembly_validation_report.json",
    }


def _pattern_registry() -> PatternRegistry:
    builtins_dir = Path(__file__).resolve().parents[2] / "runtime_kernel" / "patterns" / "builtins"
    return PatternRegistry(builtins_dir=builtins_dir)


def _graph_node_ids(state: FactoryGraphState) -> set[str]:
    graph_behavior = dict(state.get("graph_behavior_plan") or {})
    return {str(item.get("node_id") or "") for item in graph_behavior.get("nodes", []) or []}


def _tool_capability_ids(state: FactoryGraphState) -> set[str]:
    tool_plan = dict(state.get("tool_capability_plan") or {})
    return {str(item.get("capability_id") or "") for item in tool_plan.get("tool_capabilities", []) or []}


def _resource_file_path(state: FactoryGraphState) -> str:
    plan = dict(state.get("resource_condition_plan") or {})
    return str(plan.get("resource_file_path") or "")


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
