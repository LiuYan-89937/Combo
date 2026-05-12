from __future__ import annotations

import json
from typing import Any

from agent_factory.factory_graph.schemas import (
    NodeToolVisibilitySpec,
    ToolCapabilityPlanningOutput,
    ToolCapabilitySpec,
)
from agent_factory.factory_graph.model_call import FactoryModelCallError, call_structured_model, model_error_patch
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.factory_graph.tools import get_factory_base_tool_ids
from agent_factory.prompts import PromptId, output_json_schema


def run(state: FactoryGraphState) -> dict:
    try:
        plan = _plan_tool_capabilities(state)
        plan = _ensure_valid_tool_capability_plan(plan, state)
    except (FactoryModelCallError, ValueError) as exc:
        return model_error_patch("tool_capability_planning", str(exc))
    return {
        "current_stage": "tool_capability_planning",
        "status": "running",
        "tool_capability_plan": plan.model_dump(mode="json"),
        "stage_log": [
            {
                "stage_id": "tool_capability_planning",
                "status": "planned",
                "message": "tool_capability_planning planned tool capability contracts.",
            }
        ],
    }


def _plan_tool_capabilities(state: FactoryGraphState) -> ToolCapabilityPlanningOutput:
    return call_structured_model(
        stage_id="tool_capability_planning",
        prompt_id=PromptId.TOOL_CAPABILITY_PLANNING,
        output_model=ToolCapabilityPlanningOutput,
        values={
            "refined_plan_text": state.get("refined_plan_text") or "",
            "graph_behavior_plan": _json_text(state.get("graph_behavior_plan") or {}),
            "node_strategy_plan": _json_text(state.get("node_strategy_plan") or {}),
            "factory_base_tool_ids": _json_text(get_factory_base_tool_ids()),
            "output_json_schema": output_json_schema(ToolCapabilityPlanningOutput),
        },
    )


def _ensure_valid_tool_capability_plan(
    plan: ToolCapabilityPlanningOutput,
    state: FactoryGraphState,
) -> ToolCapabilityPlanningOutput:
    graph_behavior = dict(state.get("graph_behavior_plan") or {})
    node_by_id = {str(node.get("node_id")): dict(node) for node in graph_behavior.get("nodes", [])}
    node_ids = set(node_by_id)
    valid_capabilities: list[ToolCapabilitySpec] = []
    seen_capability_ids: set[str] = set()
    for capability in plan.tool_capabilities:
        capability_id = capability.capability_id.strip()
        if not capability_id or capability_id in seen_capability_ids:
            continue
        required_by = _valid_node_refs(capability.required_by_node_ids, node_ids)
        visible_to = _valid_node_refs(capability.visible_to_node_ids, node_ids)
        if not required_by and not visible_to:
            continue
        seen_capability_ids.add(capability_id)
        valid_capabilities.append(
            capability.model_copy(
                update={
                    "capability_id": capability_id,
                    "required_by_node_ids": required_by,
                    "visible_to_node_ids": visible_to or required_by,
                }
            )
        )
    capability_ids = {capability.capability_id for capability in valid_capabilities}
    visibility_by_node = {
        item.node_id: _valid_visibility(item, node_ids=node_ids, capability_ids=capability_ids)
        for item in plan.node_tool_visibility
        if item.node_id in node_ids
    }
    missing_visibility = sorted(set(node_by_id) - set(visibility_by_node))
    if missing_visibility:
        raise ValueError(f"tool capability plan missing node_tool_visibility for nodes: {missing_visibility}")
    return plan.model_copy(
        update={
            "tool_capabilities": valid_capabilities,
            "node_tool_visibility": [visibility_by_node[node_id] for node_id in node_by_id],
        }
    )


def _valid_visibility(
    item: NodeToolVisibilitySpec,
    *,
    node_ids: set[str],
    capability_ids: set[str],
) -> NodeToolVisibilitySpec:
    return item.model_copy(
        update={
            "allowed_tool_capability_ids": _valid_capability_refs(
                item.allowed_tool_capability_ids,
                capability_ids,
            ),
            "approval_required_capability_ids": _valid_capability_refs(
                item.approval_required_capability_ids,
                capability_ids,
            ),
            "blocked_tool_capability_ids": _valid_capability_refs(
                item.blocked_tool_capability_ids,
                capability_ids,
            ),
        }
    )

def _valid_node_refs(values: list[str], node_ids: set[str]) -> list[str]:
    return [value for value in values if value in node_ids]


def _valid_capability_refs(values: list[str], capability_ids: set[str]) -> list[str]:
    return [value for value in values if value in capability_ids]


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
