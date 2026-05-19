from __future__ import annotations

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from typing import Annotated, Any, TypedDict
import operator


class FactoryGraphState(TypedDict, total=False):
    factory_run_id: str
    requirement: str
    force_manufacture: bool
    interaction_mode: str
    messages: Annotated[list[BaseMessage], add_messages]
    current_stage: str
    status: str
    graph_control: dict[str, Any]
    model_activity: list[dict[str, Any]]
    capture_intent: dict[str, Any]
    factory_response: dict[str, Any]
    stage_log: Annotated[list[dict[str, Any]], operator.add]
    requirement_capture: dict[str, Any]
    requirement_brief: dict[str, Any]
    business_plan_review: dict[str, Any]
    refined_plan_text: str
    runtime_pattern_selection: dict[str, Any]
    runtime_pattern_summary: str
    pattern_structure_summary: dict[str, Any]
    graph_behavior_plan: dict[str, Any]
    node_strategy_plan: dict[str, Any]
    tool_capability_plan: dict[str, Any]
    resource_condition_plan: dict[str, Any]
    resource_file_path: str
    sandbox_contract_path: str
    resource_preparation_report_path: str
    assembly_react_attempt: int
    assembly_react_decision: dict[str, Any]
    assembly_spec_draft_candidate: dict[str, Any]
    assembly_spec_draft: dict[str, Any]
    assembly_spec_draft_path: str
    assembly_validation_observation: dict[str, Any]
    assembly_validation_report: dict[str, Any]
    assembly_validation_report_path: str
    package_materialization_plan: dict[str, Any]
    package_materialization_plan_path: str
    render_manifest: dict[str, Any]
    render_manifest_path: str
    package_validation_observation: dict[str, Any]
    package_revision_attempt: int
    package_generation: dict[str, Any]
    harness_generation: dict[str, Any]
    harness_validation_observation: dict[str, Any]
    harness_revision_attempt: int
    harness_report: dict[str, Any]
    harness_scenarios: list[dict[str, Any]]
    finalization_report: dict[str, Any]
    assembly_spec: dict[str, Any]
    errors: Annotated[list[dict[str, Any]], operator.add]
