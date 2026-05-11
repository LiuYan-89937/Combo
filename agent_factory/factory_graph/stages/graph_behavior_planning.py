from __future__ import annotations

from pathlib import Path
import json
from typing import Any

from agent_factory.factory_graph.schemas import (
    GraphBehaviorPlanOutput,
    GraphBehaviorTerminationPlan,
)
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import (
    PromptId,
    get_prompt,
    output_json_schema,
)
from agent_factory.runtime_kernel.patterns import PatternRegistry, PatternStructureSummary


def run(state: FactoryGraphState) -> dict:
    registry = _load_pattern_registry()
    selection = dict(state.get("runtime_pattern_selection") or {})
    pattern_id = str(selection.get("selected_pattern_id") or "react_agent")
    structure_summary = registry.get_structure_summary(pattern_id)
    behavior_plan = _plan_graph_behavior(state, structure_summary)
    behavior_plan = _ensure_valid_behavior_plan(behavior_plan, structure_summary)
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
    state: FactoryGraphState,
    structure_summary: PatternStructureSummary,
) -> GraphBehaviorPlanOutput:
    fallback = _fallback_graph_behavior_plan(structure_summary)
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        return fallback
    try:
        prompt_value = get_prompt(PromptId.GRAPH_BEHAVIOR_PLANNING).invoke(
            {
                "refined_plan_text": state.get("refined_plan_text") or "",
                "runtime_pattern_selection": _json_text(state.get("runtime_pattern_selection") or {}),
                "pattern_structure_summary": _json_text(structure_summary.model_dump(mode="json")),
                "output_json_schema": output_json_schema(GraphBehaviorPlanOutput),
            }
        )
        structured_model = model.with_structured_output(
            GraphBehaviorPlanOutput,
            method="json_mode",
        ).with_config(tags=["nostream"])
        if settings.max_tokens is not None:
            structured_model = structured_model.bind(max_tokens=settings.max_tokens)
        return structured_model.invoke(prompt_value)
    except Exception:
        return fallback


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
        fallback_nodes = _fallback_graph_behavior_plan(structure_summary).nodes
        known_ids = {node.node_id for node in valid_nodes}
        valid_nodes.extend(node for node in fallback_nodes if node.node_id not in known_ids)
    valid_routes = [
        route for route in behavior_plan.routes
        if (route.from_node, route.to_node, route.condition) in route_keys
    ]
    if len(valid_routes) != len(route_keys):
        fallback_routes = _fallback_graph_behavior_plan(structure_summary).routes
        known_routes = {
            (route.from_node, route.to_node, route.condition)
            for route in valid_routes
        }
        valid_routes.extend(
            route for route in fallback_routes
            if (route.from_node, route.to_node, route.condition) not in known_routes
        )
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


def _fallback_graph_behavior_plan(
    structure_summary: PatternStructureSummary,
) -> GraphBehaviorPlanOutput:
    return GraphBehaviorPlanOutput(
        pattern_id=structure_summary.pattern_id,
        pattern_name=structure_summary.name,
        graph_intent=(
            f"该 Agent 将使用 {structure_summary.name} pattern 运行，按既有图结构推进本轮任务。"
        ),
        nodes=[
            {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "business_behavior": f"执行 {node.impl} 对应的标准图行为。",
                "input_expectation": "读取 RuntimeState 中与本节点相关的上下文。",
                "output_expectation": "写入本节点职责范围内的状态更新或路由信号。",
                "user_visible": node.node_type in {"cognitive", "terminal"},
                "notes": ["fallback node behavior generated from pattern structure summary"],
            }
            for node in structure_summary.nodes
        ],
        routes=[
            {
                "from_node": route.from_node,
                "to_node": route.to_node,
                "condition": route.condition,
                "business_meaning": f"当路由条件为 {route.condition} 时，从 {route.from_node} 进入 {route.to_node}。",
                "expected_usage": "由 RuntimeKernel route decision 驱动。",
            }
            for route in structure_summary.routes
        ],
        interrupts=[
            {
                "node_id": node_id,
                "business_reason": "该节点可能需要暂停等待用户或策略输入。",
                "user_visible_reason": "运行需要用户确认、审批或补充信息。",
            }
            for node_id in structure_summary.interrupt_points
        ],
        termination={
            "success_nodes": structure_summary.termination.success_nodes,
            "failure_nodes": structure_summary.termination.failure_nodes,
            "business_success_meaning": "本轮运行到达成功终止节点。",
            "business_failure_meaning": "本轮运行到达失败终止节点，或通过 trace/status 表达失败原因。",
        },
        assumptions=["model unavailable or invalid; generated graph behavior from pattern structure summary"],
        open_questions=[],
    )


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
