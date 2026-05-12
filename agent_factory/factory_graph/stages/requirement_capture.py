from __future__ import annotations

from agent_factory.factory_graph.stage_subgraphs.business_plan_review import (
    run_business_plan_review_subgraph,
)
from agent_factory.factory_graph.stage_subgraphs.requirement_clarification import (
    run_requirement_capture_subgraph,
)
from agent_factory.factory_graph.state import FactoryGraphState


def run(state: FactoryGraphState) -> dict:
    captured = run_requirement_capture_subgraph(state)
    requirement_brief = captured.get("requirement_brief") or {}
    if requirement_brief.get("status") != "captured":
        return captured
    state_after_capture = {**state, **captured}
    reviewed = run_business_plan_review_subgraph(state_after_capture)
    return _merge_stage_patches(captured, reviewed)


def _merge_stage_patches(first: dict, second: dict) -> dict:
    merged = {
        **first,
        **second,
        "current_stage": "requirement_capture",
    }
    stage_log = []
    stage_log.extend(first.get("stage_log", []))
    stage_log.extend(second.get("stage_log", []))
    if stage_log:
        merged["stage_log"] = stage_log
    return merged
