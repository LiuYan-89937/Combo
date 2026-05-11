from __future__ import annotations

import json
from typing import Any

from agent_factory.factory_graph.schemas import (
    NodeToolVisibilitySpec,
    ToolCapabilityPlanningOutput,
    ToolCapabilitySpec,
)
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.factory_graph.tools import get_factory_base_tool_ids
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import PromptId, get_prompt, output_json_schema


def run(state: FactoryGraphState) -> dict:
    plan = _plan_tool_capabilities(state)
    plan = _ensure_valid_tool_capability_plan(plan, state)
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
    fallback = _fallback_tool_capability_plan(state)
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        return fallback
    try:
        prompt_value = get_prompt(PromptId.TOOL_CAPABILITY_PLANNING).invoke(
            {
                "refined_plan_text": state.get("refined_plan_text") or "",
                "graph_behavior_plan": _json_text(state.get("graph_behavior_plan") or {}),
                "node_strategy_plan": _json_text(state.get("node_strategy_plan") or {}),
                "factory_base_tool_ids": _json_text(get_factory_base_tool_ids()),
                "output_json_schema": output_json_schema(ToolCapabilityPlanningOutput),
            }
        )
        structured_model = model.with_structured_output(
            ToolCapabilityPlanningOutput,
            method="json_mode",
        ).with_config(tags=["nostream"])
        if settings.max_tokens is not None:
            structured_model = structured_model.bind(max_tokens=settings.max_tokens)
        return structured_model.invoke(prompt_value)
    except Exception:
        return fallback


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
    for node_id, node in node_by_id.items():
        if node_id not in visibility_by_node:
            visibility_by_node[node_id] = _fallback_visibility_for_node(
                node_id=node_id,
                node_type=str(node.get("node_type") or ""),
                capabilities=valid_capabilities,
            )
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


def _fallback_tool_capability_plan(state: FactoryGraphState) -> ToolCapabilityPlanningOutput:
    graph_behavior = dict(state.get("graph_behavior_plan") or {})
    nodes = [dict(node) for node in graph_behavior.get("nodes", [])]
    capabilities = [
        _fallback_capability_for_node(node)
        for node in nodes
        if _node_needs_tool_capability(node, state)
    ]
    return ToolCapabilityPlanningOutput(
        plan_intent="模型不可用或输出无效时，按节点行为和工具可见性策略生成最小工具能力契约。",
        tool_capabilities=capabilities,
        node_tool_visibility=[
            _fallback_visibility_for_node(
                node_id=str(node.get("node_id") or ""),
                node_type=str(node.get("node_type") or ""),
                capabilities=capabilities,
            )
            for node in nodes
        ],
        assumptions=["model unavailable or invalid; generated minimal tool capability plan"],
        open_questions=[],
    )


def _fallback_capability_for_node(node: dict[str, Any]) -> ToolCapabilitySpec:
    node_id = str(node.get("node_id") or "")
    behavior = str(node.get("business_behavior") or f"{node_id} 节点需要的工具能力")
    capability_id = f"{node_id}.tool_capability"
    return ToolCapabilitySpec(
        capability_id=capability_id,
        name=f"{node_id} 节点工具能力",
        description=f"支持 {behavior}",
        required_by_node_ids=[node_id],
        visible_to_node_ids=[node_id],
        approval_required=True,
        risk_notes=["具体风险等级由第六阶段资源和条件规划继续确认。"],
        input_contract={},
        output_contract={},
        implementation_status="unknown",
        implementation_notes=["后续阶段需要判断是绑定已有能力、生成工具代码，还是接入外部资源。"],
    )


def _fallback_visibility_for_node(
    *,
    node_id: str,
    node_type: str,
    capabilities: list[ToolCapabilitySpec],
) -> NodeToolVisibilitySpec:
    allowed = [
        capability.capability_id
        for capability in capabilities
        if node_id in capability.visible_to_node_ids
    ]
    approval_required = [
        capability.capability_id
        for capability in capabilities
        if node_id in capability.visible_to_node_ids and capability.approval_required
    ]
    return NodeToolVisibilitySpec(
        node_id=node_id,
        allowed_tool_capability_ids=allowed,
        approval_required_capability_ids=approval_required,
        blocked_tool_capability_ids=[],
        reason=(
            "该节点按第四阶段工具可见性策略开放最小工具能力。"
            if allowed
            else f"{node_type or 'unknown'} 节点当前不暴露工具能力。"
        ),
    )


def _node_needs_tool_capability(node: dict[str, Any], state: FactoryGraphState) -> bool:
    node_id = str(node.get("node_id") or "")
    if str(node.get("node_type") or "") == "operational":
        return True
    node_strategy_plan = dict(state.get("node_strategy_plan") or {})
    for item in node_strategy_plan.get("node_strategies", []) or []:
        if str(item.get("node_id") or "") != node_id:
            continue
        for strategy_ref in item.get("strategy_refs", []) or []:
            if strategy_ref.get("kind") == "tool_visibility":
                strategy_id = str(strategy_ref.get("strategy_id") or "")
                return strategy_id != "tool.visibility.none"
    return False


def _valid_node_refs(values: list[str], node_ids: set[str]) -> list[str]:
    return [value for value in values if value in node_ids]


def _valid_capability_refs(values: list[str], capability_ids: set[str]) -> list[str]:
    return [value for value in values if value in capability_ids]


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
