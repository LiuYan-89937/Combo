from __future__ import annotations

import json
from typing import Any

from agent_factory.factory_graph.schemas import (
    NodeStrategyRef,
    NodeStrategyPlan,
    NodeStrategyPlanningOutput,
    NodeWrapperPlan,
    ProposedNodeStrategySpec,
)
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.factory_graph.strategy_catalog import (
    DEFAULT_FACTORY_STRATEGY_CATALOG,
    FactoryStrategyCatalog,
)
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import (
    PromptId,
    get_prompt,
    output_json_schema,
)
from agent_factory.runtime_kernel.patterns.schema import PatternNodeWrapperSpec
from agent_factory.runtime_kernel.wrappers import DEFAULT_NODE_WRAPPER_REGISTRY


def run(state: FactoryGraphState) -> dict:
    wrapper_catalog = _wrapper_catalog()
    strategy_catalog = DEFAULT_FACTORY_STRATEGY_CATALOG
    strategy_plan = _plan_node_strategies(
        state,
        wrapper_catalog=wrapper_catalog,
        strategy_catalog=strategy_catalog,
    )
    strategy_plan = _ensure_valid_strategy_plan(
        strategy_plan,
        state,
        wrapper_catalog=wrapper_catalog,
    )
    return {
        "current_stage": "node_strategy_planning",
        "status": "running",
        "node_strategy_plan": strategy_plan.model_dump(mode="json"),
        "stage_log": [
            {
                "stage_id": "node_strategy_planning",
                "status": "planned",
                "message": "node_strategy_planning planned node strategies.",
            }
        ],
    }


def _plan_node_strategies(
    state: FactoryGraphState,
    *,
    wrapper_catalog: list[dict[str, Any]],
    strategy_catalog: FactoryStrategyCatalog,
) -> NodeStrategyPlanningOutput:
    fallback = _fallback_node_strategy_plan(state)
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        return fallback
    try:
        prompt_value = get_prompt(PromptId.NODE_STRATEGY_PLANNING).invoke(
            {
                "refined_plan_text": state.get("refined_plan_text") or "",
                "runtime_pattern_selection": _json_text(state.get("runtime_pattern_selection") or {}),
                "graph_behavior_plan": _json_text(state.get("graph_behavior_plan") or {}),
                "pattern_structure_summary": _json_text(state.get("pattern_structure_summary") or {}),
                "wrapper_catalog": _json_text(wrapper_catalog),
                "strategy_catalog": _json_text(strategy_catalog.as_prompt_payload()),
                "output_json_schema": output_json_schema(NodeStrategyPlanningOutput),
            }
        )
        structured_model = model.with_structured_output(
            NodeStrategyPlanningOutput,
            method="json_mode",
        ).with_config(tags=["nostream"])
        if settings.max_tokens is not None:
            structured_model = structured_model.bind(max_tokens=settings.max_tokens)
        return structured_model.invoke(prompt_value)
    except Exception:
        return fallback


def _ensure_valid_strategy_plan(
    strategy_plan: NodeStrategyPlanningOutput,
    state: FactoryGraphState,
    *,
    wrapper_catalog: list[dict[str, Any]],
) -> NodeStrategyPlanningOutput:
    graph_behavior = dict(state.get("graph_behavior_plan") or {})
    node_by_id = {str(node.get("node_id")): dict(node) for node in graph_behavior.get("nodes", [])}
    node_ids = set(node_by_id)
    allowed_wrappers = {
        item["wrapper_id"]: set(item.get("phases", []))
        for item in wrapper_catalog
    }
    proposed_strategies = _valid_proposed_strategies(strategy_plan.proposed_strategies, node_ids)
    proposed_by_id = {item.strategy_id: item for item in proposed_strategies}
    valid_node_strategies: list[NodeStrategyPlan] = []
    for item in strategy_plan.node_strategies:
        expected_node = node_by_id.get(item.node_id)
        if expected_node is None:
            continue
        valid_wrappers = [
            wrapper for wrapper in item.wrappers
            if _valid_wrapper_plan(wrapper, allowed_wrappers)
        ]
        valid_strategy_refs = [
            strategy_ref for strategy_ref in item.strategy_refs
            if _valid_strategy_ref(strategy_ref, proposed_by_id)
        ]
        valid_node_strategies.append(
            item.model_copy(
                update={
                    "node_type": str(expected_node.get("node_type") or item.node_type),
                    "wrappers": valid_wrappers,
                    "strategy_refs": valid_strategy_refs,
                }
            )
        )
    existing = {item.node_id for item in valid_node_strategies}
    for node_id, node in node_by_id.items():
        if node_id not in existing:
            valid_node_strategies.append(_fallback_node_strategy(node))
    return strategy_plan.model_copy(
        update={
            "pattern_id": str(graph_behavior.get("pattern_id") or strategy_plan.pattern_id),
            "node_strategies": valid_node_strategies,
            "proposed_strategies": proposed_strategies,
        }
    )


def _valid_wrapper_plan(wrapper: NodeWrapperPlan, allowed_wrappers: dict[str, set[str]]) -> bool:
    phases = allowed_wrappers.get(wrapper.wrapper_id)
    if phases is None or wrapper.phase not in phases:
        return False
    try:
        DEFAULT_NODE_WRAPPER_REGISTRY.validate_spec(
            PatternNodeWrapperSpec(
                id=wrapper.wrapper_id,
                phase=wrapper.phase,
                config=dict(wrapper.config),
            )
        )
    except Exception:
        return False
    return True


def _valid_proposed_strategies(
    proposed_strategies: list[ProposedNodeStrategySpec],
    node_ids: set[str],
) -> list[ProposedNodeStrategySpec]:
    valid_items: list[ProposedNodeStrategySpec] = []
    seen: set[str] = set()
    for item in proposed_strategies:
        if item.strategy_id in seen or DEFAULT_FACTORY_STRATEGY_CATALOG.has(item.strategy_id):
            continue
        required_by = [node_id for node_id in item.required_by_node_ids if node_id in node_ids]
        if not required_by:
            continue
        seen.add(item.strategy_id)
        valid_items.append(item.model_copy(update={"required_by_node_ids": required_by}))
    return valid_items


def _valid_strategy_ref(
    strategy_ref: NodeStrategyRef,
    proposed_by_id: dict[str, ProposedNodeStrategySpec],
) -> bool:
    if strategy_ref.source == "catalog":
        catalog_item = DEFAULT_FACTORY_STRATEGY_CATALOG.get(strategy_ref.strategy_id)
        if catalog_item is None:
            return False
        return catalog_item.kind == strategy_ref.kind and catalog_item.phase == strategy_ref.phase
    proposed = proposed_by_id.get(strategy_ref.strategy_id)
    if proposed is None:
        return False
    return proposed.kind == strategy_ref.kind and proposed.phase == strategy_ref.phase


def _fallback_node_strategy_plan(state: FactoryGraphState) -> NodeStrategyPlanningOutput:
    graph_behavior = dict(state.get("graph_behavior_plan") or {})
    nodes = [dict(node) for node in graph_behavior.get("nodes", [])]
    return NodeStrategyPlanningOutput(
        pattern_id=str(graph_behavior.get("pattern_id") or ""),
        strategy_intent="模型不可用或输出无效时，按策略目录生成最小可装配策略引用。",
        node_strategies=[_fallback_node_strategy(node) for node in nodes],
        proposed_strategies=[],
        global_assumptions=["model unavailable or invalid; generated catalog-based minimal node strategies"],
        open_questions=[],
    )


def _fallback_node_strategy(node: dict[str, Any]) -> NodeStrategyPlan:
    node_id = str(node.get("node_id") or "")
    node_type = str(node.get("node_type") or "")
    wrappers = _default_wrappers_for_node(node_id=node_id, node_type=node_type)
    return NodeStrategyPlan(
        node_id=node_id,
        node_type=node_type,
        business_behavior_ref=str(node.get("business_behavior") or ""),
        wrappers=wrappers,
        strategy_refs=_catalog_strategy_refs_for_node(node_id=node_id, node_type=node_type),
        assumptions=["fallback node strategy refs generated from graph behavior plan"],
        open_questions=[],
    )


def _default_wrappers_for_node(*, node_id: str, node_type: str) -> list[NodeWrapperPlan]:
    wrappers: list[NodeWrapperPlan] = []
    if node_type == "cognitive":
        wrappers.append(
            NodeWrapperPlan(
                wrapper_id="context.prepare_model_context",
                phase="before",
                purpose="在认知节点执行前准备模型上下文。",
                config={"include_user_config": True, "include_user_profile": True},
                config_notes={},
            )
        )
    if node_type == "operational":
        wrappers.append(
            NodeWrapperPlan(
                wrapper_id="context.prepare_tool_context",
                phase="before",
                purpose="在操作节点执行前准备工具上下文。",
                config={},
                config_notes={},
            )
        )
    if node_id in {"answer", "commit", "finalize"}:
        wrappers.append(
            NodeWrapperPlan(
                wrapper_id="memory.summary_every_n",
                phase="after",
                purpose="在关键输出节点之后按阈值压缩会话记忆。",
                config={"every_messages": 100, "keep_recent": 20},
                config_notes={},
            )
        )
    return wrappers


def _catalog_strategy_refs_for_node(*, node_id: str, node_type: str) -> list[NodeStrategyRef]:
    refs: list[NodeStrategyRef] = []
    if node_type == "cognitive":
        refs.append(
            NodeStrategyRef(
                strategy_id="context.model.reasoning_brief",
                kind="context",
                phase="before",
                purpose="准备模型推理所需的需求、计划和会话摘要。",
                config={"include_memory_summary": True, "include_runtime_config": True},
            )
        )
        refs.append(
            NodeStrategyRef(
                strategy_id="memory.session.read_recent",
                kind="memory",
                phase="before",
                purpose="读取最近会话记忆供认知节点使用。",
                config={"limit": 5},
            )
        )
        refs.append(
            NodeStrategyRef(
                strategy_id="tool.visibility.none",
                kind="tool_visibility",
                phase="before",
                purpose="认知节点默认不直接暴露工具能力，后续工具规划阶段可调整。",
                config={},
            )
        )
    if node_type == "operational":
        refs.append(
            NodeStrategyRef(
                strategy_id="context.tool.execution_scope",
                kind="context",
                phase="before",
                purpose="准备工具执行所需的最小上下文。",
                config={"include_approval_payload": True, "include_tool_capability_refs": True},
            )
        )
        refs.append(
            NodeStrategyRef(
                strategy_id="tool.visibility.node_scoped",
                kind="tool_visibility",
                phase="before",
                purpose="只暴露后续工具规划阶段允许给该节点的能力引用。",
                config={"allowed_tool_capability_refs": [], "approval_required": True},
                config_notes={"allowed_tool_capability_refs": "由第五阶段 tool_capability_planning 细化"},
            )
        )
    if node_id in {"answer", "commit", "finalize"}:
        refs.append(
            NodeStrategyRef(
                strategy_id="memory.session.write_turn_summary",
                kind="memory",
                phase="after",
                purpose="在关键输出后写入本轮摘要。",
                config={"max_chars": 1200},
            )
        )
        refs.append(
            NodeStrategyRef(
                strategy_id="policy.output.contract_check",
                kind="policy",
                phase="after",
                purpose="检查最终输出契约。",
                config={},
                config_notes={"output_contract": "由 assembly_spec_generation 固化"},
            )
        )
    if not refs:
        refs.append(
            NodeStrategyRef(
                strategy_id="tool.visibility.none",
                kind="tool_visibility",
                phase="before",
                purpose="该节点不暴露工具能力。",
                config={},
            )
        )
    return refs


def _wrapper_catalog() -> list[dict[str, Any]]:
    catalog = []
    for wrapper_id in DEFAULT_NODE_WRAPPER_REGISTRY.list_wrapper_ids():
        wrapper_cls = DEFAULT_NODE_WRAPPER_REGISTRY.get(wrapper_id)
        catalog.append(
            {
                "wrapper_id": wrapper_id,
                "phases": sorted(wrapper_cls.supported_phases),
                "reads": sorted(wrapper_cls.readable_sections),
                "writes": sorted(wrapper_cls.writable_sections),
                "description": wrapper_cls.description,
                "config_schema": (
                    wrapper_cls.config_schema.model_json_schema()
                    if wrapper_cls.config_schema is not None
                    else {}
                ),
            }
        )
    return catalog


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
