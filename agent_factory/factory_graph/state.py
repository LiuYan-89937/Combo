from __future__ import annotations

from langchain_core.messages import BaseMessage

from typing import Annotated, Any, TypedDict
import operator


class FactoryGraphState(TypedDict, total=False):
    requirement: str
    force_manufacture: bool
    interaction_mode: str
    messages: Annotated[list[BaseMessage], operator.add]
    current_stage: str
    status: str
    graph_control: dict[str, Any]
    protected_tool_ids: list[str]
    tool_approval: dict[str, Any]
    capture_intent: dict[str, Any]
    factory_response: dict[str, Any]
    stage_log: Annotated[list[dict[str, Any]], operator.add]
    requirement_capture: dict[str, Any]
    requirement_brief: dict[str, Any]
    business_plan_review: dict[str, Any]
    refined_plan_text: str
    runtime_pattern_selection: dict[str, Any]
    graph_behavior_plan: dict[str, Any]
    node_strategy_plan: dict[str, Any]
    tool_capability_plan: dict[str, Any]
    resource_condition_plan: dict[str, Any]
    assembly_spec_draft: dict[str, Any]
    package_generation: dict[str, Any]
    harness_report: dict[str, Any]
    harness_scenarios: list[dict[str, Any]]
    finalization_report: dict[str, Any]
    assembly_spec: dict[str, Any]
    errors: Annotated[list[dict[str, Any]], operator.add]
