from __future__ import annotations

from agent_factory.runtime_kernel.planning import RUNTIME_PLAN_TOOL_ID
from agent_factory.runtime_kernel.capability_state import require_bound_tool_ids
from agent_factory.runtime_kernel.state import RuntimeState


PLAN_EXECUTE_PLANNER_NODE_ID = "planner"
PLAN_EXECUTE_EXECUTOR_NODE_ID = "executor"
PLAN_EXECUTE_CASUAL_NODE_ID = "casual_react"
PLAN_EXECUTE_PLANNER_INSPECTION_TOOL_IDS = frozenset(
    {
        "delegation_status",
        "glob",
        "grep",
        "ls",
        "read",
    }
)
PLAN_EXECUTE_NODE_IDS = frozenset(
    {
        PLAN_EXECUTE_PLANNER_NODE_ID,
        PLAN_EXECUTE_EXECUTOR_NODE_ID,
        PLAN_EXECUTE_CASUAL_NODE_ID,
    }
)


def plan_and_execute_model_tool_ids(
    *,
    node_id: str,
    state: RuntimeState,
) -> list[str]:
    frozen_tool_ids = available_tool_ids(state)
    if node_id == PLAN_EXECUTE_PLANNER_NODE_ID:
        return [RUNTIME_PLAN_TOOL_ID, *_planner_inspection_tool_ids(frozen_tool_ids)]
    if node_id == PLAN_EXECUTE_EXECUTOR_NODE_ID:
        return [RUNTIME_PLAN_TOOL_ID, *frozen_tool_ids]
    if node_id == PLAN_EXECUTE_CASUAL_NODE_ID:
        return frozen_tool_ids
    return []


def plan_and_execute_delegated_tool_ids(
    *,
    origin_node_id: str,
    state: RuntimeState,
) -> list[str]:
    if origin_node_id == PLAN_EXECUTE_PLANNER_NODE_ID:
        return _planner_inspection_tool_ids(available_tool_ids(state))
    if origin_node_id in {
        PLAN_EXECUTE_EXECUTOR_NODE_ID,
        PLAN_EXECUTE_CASUAL_NODE_ID,
    }:
        return available_tool_ids(state)
    return []


def plan_and_execute_runtime_plan_tool_ids(*, origin_node_id: str) -> list[str]:
    if origin_node_id in {PLAN_EXECUTE_PLANNER_NODE_ID, PLAN_EXECUTE_EXECUTOR_NODE_ID}:
        return [RUNTIME_PLAN_TOOL_ID]
    return []


def available_tool_ids(state: RuntimeState) -> list[str]:
    return without_runtime_plan(merge_tool_ids(require_bound_tool_ids(state)))


def _planner_inspection_tool_ids(frozen_tool_ids: list[str]) -> list[str]:
    return [
        tool_id
        for tool_id in frozen_tool_ids
        if tool_id in PLAN_EXECUTE_PLANNER_INSPECTION_TOOL_IDS
    ]


def merge_tool_ids(tool_ids: list[str]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for tool_id in tool_ids:
        item = str(tool_id).strip()
        if item and item not in seen:
            items.append(item)
            seen.add(item)
    return items


def without_runtime_plan(tool_ids: list[str]) -> list[str]:
    return [tool_id for tool_id in tool_ids if tool_id != RUNTIME_PLAN_TOOL_ID]
