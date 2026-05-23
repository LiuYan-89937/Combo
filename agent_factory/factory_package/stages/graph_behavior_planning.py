from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from agent_factory.factory_package.schemas import (
    GraphBehaviorPlanOutput,
    GraphBehaviorTerminationPlan,
)
from agent_factory.factory_package.model_call import FactoryModelCallError, call_structured_model, model_error_patch
from agent_factory.factory_package.state import FactoryPackageState
from agent_factory.prompts import (
    PromptId,
    output_json_schema,
)
from agent_factory.runtime_kernel.patterns import PatternRegistry, PatternStructureSummary


def run(state: FactoryPackageState) -> dict:
    registry = _load_pattern_registry()
    selection = dict(state.get("runtime_pattern_selection") or {})
    pattern_id = str(selection.get("selected_pattern_id") or "react_agent")
    structure_summary = registry.get_structure_summary(pattern_id)
    try:
        behavior_plan = _plan_graph_behavior(state, structure_summary)
        behavior_plan = _ensure_valid_behavior_plan(behavior_plan, structure_summary)
    except (FactoryModelCallError, ValueError) as exc:
        return model_error_patch("graph_behavior_planning", str(exc))
    return {
        "current_stage": "graph_behavior_planning",
        "status": "running",
        "pattern_structure_summary": structure_summary.model_dump(mode="json"),
        "graph_behavior_plan": behavior_plan.model_dump(mode="json"),
        "stage_log": [
            {
                "stage_id": "graph_behavior_planning",
                "status": "planned",
                "message": f"graph_behavior_planning planned graph behavior for {pattern_id}.",
            }
        ],
    }


def _load_pattern_registry() -> PatternRegistry:
    builtins_dir = Path(__file__).resolve().parents[2] / "runtime_kernel" / "patterns" / "builtins"
    return PatternRegistry(builtins_dir=builtins_dir)


def _plan_graph_behavior(
    state: FactoryPackageState,
    structure_summary: PatternStructureSummary,
) -> GraphBehaviorPlanOutput:
    return call_structured_model(
        stage_id="graph_behavior_planning",
        prompt_id=PromptId.GRAPH_BEHAVIOR_PLANNING,
        output_model=GraphBehaviorPlanOutput,
        values={
            "refined_plan_text": state.get("refined_plan_text") or "",
            "runtime_pattern_selection": _json_text(state.get("runtime_pattern_selection") or {}),
            "pattern_structure_summary": _json_text(structure_summary.model_dump(mode="json")),
            "output_json_schema": output_json_schema(GraphBehaviorPlanOutput),
        },
    )


def _ensure_valid_behavior_plan(
    behavior_plan: GraphBehaviorPlanOutput,
    structure_summary: PatternStructureSummary,
) -> GraphBehaviorPlanOutput:
    node_by_id = {node.node_id: node for node in structure_summary.nodes}
    route_keys = {
        (route.from_node, route.to_node, route.condition)
        for route in structure_summary.routes
    }
    valid_nodes = [
        node for node in behavior_plan.nodes
        if node.node_id in node_by_id and node.node_type == node_by_id[node.node_id].node_type
    ]
    if len(valid_nodes) != len(node_by_id):
        missing = sorted(set(node_by_id) - {node.node_id for node in valid_nodes})
        raise ValueError(f"graph behavior plan missing or invalid node plans: {missing}")
    valid_routes = [
        route for route in behavior_plan.routes
        if (route.from_node, route.to_node, route.condition) in route_keys
    ]
    if len(valid_routes) != len(route_keys):
        raise ValueError("graph behavior plan routes must exactly match selected pattern routes")
    valid_interrupts = [
        interrupt for interrupt in behavior_plan.interrupts
        if interrupt.node_id in structure_summary.interrupt_points
    ]
    return behavior_plan.model_copy(
        update={
            "pattern_id": structure_summary.pattern_id,
            "pattern_name": structure_summary.name,
            "nodes": valid_nodes,
            "routes": valid_routes,
            "interrupts": valid_interrupts,
            "termination": GraphBehaviorTerminationPlan(
                success_nodes=structure_summary.termination.success_nodes,
                failure_nodes=structure_summary.termination.failure_nodes,
                business_success_meaning=behavior_plan.termination.business_success_meaning,
                business_failure_meaning=behavior_plan.termination.business_failure_meaning,
            ),
        }
    )

def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
