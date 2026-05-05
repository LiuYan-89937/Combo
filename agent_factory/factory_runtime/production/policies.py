from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.factory_runtime.production.state import (
    FactoryProductionState,
    FactoryProductionStateDict,
)


BOOKKEEPING_FIELDS = {
    "run_id",
    "status",
    "current_stage",
    "graph_node",
    "context_envelopes",
    "decision_records",
    "events",
    "error",
    "stage_history",
}


class FactoryNodeAccessPolicy(BaseModel):
    """Project Factory graph state to node-visible typed artifacts.

    Nodes are intentionally given a projected state instead of the full graph
    state. The wrapper then merges back only fields the node is allowed to
    change, so a node cannot accidentally depend on raw upstream payloads or
    mutate unrelated artifacts.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    allowed_reads: dict[str, set[str]] = Field(default_factory=lambda: _allowed_reads())
    allowed_writes: dict[str, set[str]] = Field(default_factory=lambda: _allowed_writes())

    def wrap(
        self,
        node_name: str,
        handler: Callable[[FactoryProductionStateDict], FactoryProductionStateDict],
    ) -> Callable[[FactoryProductionStateDict], FactoryProductionStateDict]:
        def guarded(raw_state: FactoryProductionStateDict) -> FactoryProductionStateDict:
            before = FactoryProductionState.from_graph_state(raw_state)
            projected = self.project(node_name, before)
            proposed = FactoryProductionState.from_graph_state(handler(projected.as_graph_state()))
            merged = self.merge(node_name, before=before, projected=projected, proposed=proposed)
            return merged.as_graph_state()

        return guarded

    def project(self, node_name: str, state: FactoryProductionState) -> FactoryProductionState:
        allowed = self._read_set(node_name)
        data = {}
        for field_name in FactoryProductionState.model_fields:
            if field_name in allowed:
                data[field_name] = getattr(state, field_name)
            else:
                data[field_name] = _field_default(field_name, state)
        return FactoryProductionState.model_validate(data)

    def merge(
        self,
        node_name: str,
        *,
        before: FactoryProductionState,
        projected: FactoryProductionState,
        proposed: FactoryProductionState,
    ) -> FactoryProductionState:
        allowed = self._write_set(node_name)
        before_data = before.model_dump(mode="python", by_alias=True)
        projected_data = projected.model_dump(mode="python", by_alias=True)
        proposed_data = proposed.model_dump(mode="python", by_alias=True)
        changed = {
            key
            for key in proposed_data
            if proposed_data.get(key) != projected_data.get(key)
        }
        disallowed = sorted(changed.difference(allowed))
        if disallowed:
            raise ValueError(
                f"{node_name} attempted to update disallowed Factory state fields: "
                + ", ".join(disallowed)
            )
        merged = {**before_data}
        for key in changed:
            merged[key] = proposed_data[key]
        return FactoryProductionState.model_validate(merged)

    def _read_set(self, node_name: str) -> set[str]:
        return set(self.allowed_reads.get(node_name, set())).union(BOOKKEEPING_FIELDS)

    def _write_set(self, node_name: str) -> set[str]:
        return set(self.allowed_writes.get(node_name, set())).union(BOOKKEEPING_FIELDS)


def _field_default(field_name: str, state: FactoryProductionState) -> Any:
    if field_name == "run_id":
        return state.run_id
    if field_name == "requirement":
        return ""
    field = FactoryProductionState.model_fields[field_name]
    if not field.is_required():
        return field.get_default(call_default_factory=True)
    return None


def _allowed_reads() -> dict[str, set[str]]:
    return {
        "capture_requirement": {"requirement", "draft"},
        "load_factory_context": set(),
        "classify_factory_intent": {"requirement"},
        "analyze_requirement": {"requirement", "factory_intent"},
        "maybe_clarify": {"clarification_questions", "clarification_options", "guidance_message"},
        "plan_capability_preconditions": {
            "requirement_understanding",
            "primitives",
        },
        "analyze_tool_preconditions": {
            "requirement",
            "primitives",
            "capability_plan",
        },
        "discover_resources": {
            "requirement",
            "primitives",
            "resource_need_plan",
        },
        "factory_web_research": {
            "requirement",
            "tool_precondition_report",
        },
        "probe_environment": {
            "requirement",
            "primitives",
            "tool_precondition_report",
            "web_research_report",
            "research_brief_report",
            "research_completeness_report",
            "resource_need_plan",
            "evidence_reports",
        },
        "enrich_tool_contracts": {
            "web_research_report",
            "research_brief_report",
            "research_completeness_report",
            "resource_contracts",
            "tool_precondition_report",
            "resource_contract_set",
            "evidence_reports",
        },
        "resolve_readiness": {
            "readiness_report",
            "readiness_decision",
            "research_completeness_report",
        },
        "plan_primitives": {
            "requirement",
            "requirement_analysis",
            "requirement_understanding",
            "capability_plan",
            "condition_plan",
            "resource_need_plan",
            "resource_contract_set",
            "readiness_decision",
            "implementation_plan",
            "evidence_reports",
        },
        "validate_primitives": {"requirement", "raw_model_data"},
        "repair_primitives": {"requirement", "raw_model_data", "repair_attempts", "max_repair_attempts"},
        "write_package": {
            "requirement",
            "primitives",
            "environment_report",
            "resource_contracts",
            "readiness_report",
            "web_research_report",
            "research_brief_report",
            "research_completeness_report",
        },
        "generate_tool_scripts": {
            "package_path",
            "primitives",
            "resource_contracts",
            "resource_contract_set",
            "implementation_plan",
            "evidence_reports",
        },
        "generate_tool_tests": {"package_path", "primitives"},
        "generate_mcp_bindings": {"package_path", "primitives"},
        "generate_harness_scenarios": {"package_path", "primitives"},
        "validate_package": {"package_path", "primitives", "validation_report", "resource_contracts"},
        "static_check_tool_scripts": {
            "package_path",
            "tool_static_check_report",
            "tool_test_report",
            "mcp_binding_report",
            "harness_dry_run_report",
        },
        "run_generated_tool_tests": {
            "package_path",
            "tool_static_check_report",
            "tool_test_report",
            "mcp_binding_report",
            "harness_dry_run_report",
            "tool_test_repair_attempts",
            "max_tool_test_repair_attempts",
        },
        "repair_tool_tests": {
            "package_path",
            "primitives",
            "tool_test_report",
            "tool_test_repair_attempts",
            "max_tool_test_repair_attempts",
        },
        "validate_mcp_bindings_local": {
            "package_path",
            "tool_static_check_report",
            "tool_test_report",
            "mcp_binding_report",
            "harness_dry_run_report",
        },
        "dry_run_harness_scenarios": {
            "package_path",
            "tool_static_check_report",
            "tool_test_report",
            "mcp_binding_report",
            "harness_dry_run_report",
        },
        "record_factory_memory": {
            "requirement",
            "package_path",
            "generated_artifacts",
            "generated_tool_count",
            "generated_tool_test_count",
            "mcp_binding_count",
            "harness_scenario_count",
            "validation_report",
            "verification_report",
            "readiness_decision",
            "production_summary",
        },
        "complete": {
            "requirement",
            "package_path",
            "generated_artifacts",
            "generated_tool_count",
            "generated_tool_test_count",
            "mcp_binding_count",
            "harness_scenario_count",
            "validation_report",
            "verification_report",
            "readiness_decision",
            "research_completeness_report",
        },
        "failed": {"requirement", "package_path"},
        "needs_clarification": {"clarification_questions", "clarification_options", "guidance_message"},
        "not_agent_request": {"guidance_message", "factory_intent"},
    }


def _allowed_writes() -> dict[str, set[str]]:
    return {
        "capture_requirement": set(),
        "load_factory_context": set(),
        "classify_factory_intent": {
            "factory_intent",
            "guidance_message",
            "clarification_questions",
            "clarification_options",
        },
        "analyze_requirement": {
            "requirement_analysis",
            "requirement_understanding",
            "clarification_questions",
            "decision_records",
        },
        "maybe_clarify": set(),
        "plan_capability_preconditions": {"capability_plan", "decision_records"},
        "analyze_tool_preconditions": {
            "tool_precondition_report",
            "condition_plan",
            "resource_need_plan",
            "decision_records",
        },
        "discover_resources": {"primitives", "resource_need_plan", "decision_records"},
        "factory_web_research": {
            "web_research_report",
            "research_brief_report",
            "research_completeness_report",
            "evidence_reports",
        },
        "probe_environment": {
            "environment_report",
            "resource_contracts",
            "readiness_report",
            "resource_contract_set",
            "readiness_decision",
            "evidence_reports",
        },
        "enrich_tool_contracts": {"implementation_plan", "decision_records"},
        "resolve_readiness": {
            "readiness_decision",
            "clarification_questions",
            "clarification_options",
        },
        "plan_primitives": {"raw_model_data"},
        "validate_primitives": {"raw_model_data", "primitives"},
        "repair_primitives": {"raw_model_data", "repair_attempts"},
        "write_package": {"package_path", "validation_report"},
        "generate_tool_scripts": {"generated_artifacts", "generated_tool_count"},
        "generate_tool_tests": {"generated_artifacts", "generated_tool_test_count"},
        "generate_mcp_bindings": {"generated_artifacts", "mcp_binding_count"},
        "generate_harness_scenarios": {"generated_artifacts", "harness_scenario_count"},
        "validate_package": {"generated_artifacts", "validation_report"},
        "static_check_tool_scripts": {
            "tool_static_check_report",
            "verification_report",
        },
        "run_generated_tool_tests": {
            "tool_test_report",
            "verification_report",
        },
        "repair_tool_tests": {
            "generated_artifacts",
            "generated_tool_test_count",
            "tool_test_repair_attempts",
        },
        "validate_mcp_bindings_local": {
            "mcp_binding_report",
            "verification_report",
        },
        "dry_run_harness_scenarios": {
            "harness_dry_run_report",
            "verification_report",
        },
        "record_factory_memory": {"production_summary", "decision_records"},
        "complete": {"status", "production_summary", "decision_records"},
        "failed": {"status", "production_summary", "decision_records"},
        "needs_clarification": {"status"},
        "not_agent_request": {"status"},
    }
