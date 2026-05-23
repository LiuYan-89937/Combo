from __future__ import annotations

import json
from typing import Any

from agent_factory.factory_package.schemas import (
    NodeStrategyPlan,
    NodeStrategyPlanningOutput,
    NodeWrapperPlan,
    ProposedNodeStrategySpec,
)
from agent_factory.factory_package.model_call import FactoryModelCallError, call_structured_model, model_error_patch
from agent_factory.factory_package.state import FactoryPackageState
from agent_factory.factory_package.strategy_catalog import (
    DEFAULT_FACTORY_STRATEGY_CATALOG,
    FactoryStrategyCatalog,
)
from agent_factory.prompts import (
    PromptId,
    output_json_schema,
)
from agent_factory.runtime_kernel.patterns.schema import PatternNodeWrapperSpec
from agent_factory.runtime_kernel.wrappers import DEFAULT_NODE_WRAPPER_REGISTRY


def run(state: FactoryPackageState) -> dict:
    wrapper_catalog = _wrapper_catalog()
    strategy_catalog = DEFAULT_FACTORY_STRATEGY_CATALOG
    try:
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
    except (FactoryModelCallError, ValueError) as exc:
        return model_error_patch("node_strategy_planning", str(exc))
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
    state: FactoryPackageState,
    *,
    wrapper_catalog: list[dict[str, Any]],
    strategy_catalog: FactoryStrategyCatalog,
) -> NodeStrategyPlanningOutput:
    return call_structured_model(
        stage_id="node_strategy_planning",
        prompt_id=PromptId.NODE_STRATEGY_PLANNING,
        output_model=NodeStrategyPlanningOutput,
        values={
            "refined_plan_text": state.get("refined_plan_text") or "",
            "runtime_pattern_selection": _json_text(state.get("runtime_pattern_selection") or {}),
            "graph_behavior_plan": _json_text(state.get("graph_behavior_plan") or {}),
            "pattern_structure_summary": _json_text(state.get("pattern_structure_summary") or {}),
            "wrapper_catalog": _json_text(wrapper_catalog),
            "strategy_catalog": _json_text(strategy_catalog.as_prompt_payload()),
            "output_json_schema": output_json_schema(NodeStrategyPlanningOutput),
        },
    )


def _ensure_valid_strategy_plan(
    strategy_plan: NodeStrategyPlanningOutput,
    state: FactoryPackageState,
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
    missing = sorted(set(node_by_id) - existing)
    if missing:
        raise ValueError(f"node strategy plan missing or invalid node strategies: {missing}")
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
