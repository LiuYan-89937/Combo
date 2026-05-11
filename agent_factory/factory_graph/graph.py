from __future__ import annotations

import uuid

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langchain_core.tools import BaseTool

from agent_factory.factory_graph.constants import STAGE_IDS
from agent_factory.factory_graph.stages import STAGE_RUNNERS
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.factory_graph.tool_approval import (
    FACTORY_TOOL_APPROVAL_NODE,
    approve_tool_calls,
    route_after_tool_approval,
)
from agent_factory.factory_graph.tools import get_factory_graph_tools, get_factory_protected_tool_ids


FACTORY_TOOLS_NODE = "factory_tools"


def build_factory_graph(
    *,
    stop_after_stage: str | None = None,
    tools: list[BaseTool] | None = None,
    enable_interrupts: bool = False,
    checkpointer: BaseCheckpointSaver | None = None,
):
    if stop_after_stage is not None and stop_after_stage not in STAGE_IDS:
        raise ValueError(f"Unknown factory stage: {stop_after_stage}")

    graph = StateGraph(FactoryGraphState)
    graph.add_node(FACTORY_TOOL_APPROVAL_NODE, approve_tool_calls)
    graph.add_node(
        FACTORY_TOOLS_NODE,
        ToolNode(tools or get_factory_graph_tools(), name=FACTORY_TOOLS_NODE),
    )
    for stage_id in STAGE_IDS:
        graph.add_node(stage_id, STAGE_RUNNERS[stage_id])

    graph.add_edge(START, STAGE_IDS[0])
    for index, stage_id in enumerate(STAGE_IDS):
        next_stage = STAGE_IDS[index + 1] if index + 1 < len(STAGE_IDS) else END
        terminal_stage = stage_id == stop_after_stage or next_stage == END
        route_after_stage = _make_stage_router(
            next_stage=END if terminal_stage else next_stage,
        )
        graph.add_conditional_edges(
            stage_id,
            route_after_stage,
            {
                FACTORY_TOOL_APPROVAL_NODE: FACTORY_TOOL_APPROVAL_NODE,
                FACTORY_TOOLS_NODE: FACTORY_TOOLS_NODE,
                next_stage: next_stage,
                END: END,
            },
        )
    graph.add_conditional_edges(
        FACTORY_TOOL_APPROVAL_NODE,
        _route_after_tool_approval,
        {
            FACTORY_TOOLS_NODE: FACTORY_TOOLS_NODE,
            **{stage_id: stage_id for stage_id in STAGE_IDS},
            END: END,
        },
    )
    graph.add_conditional_edges(
        FACTORY_TOOLS_NODE,
        _route_after_tools,
        {stage_id: stage_id for stage_id in STAGE_IDS} | {END: END},
    )
    resolved_checkpointer = checkpointer if checkpointer is not None else _default_checkpointer(enable_interrupts)
    return graph.compile(checkpointer=resolved_checkpointer)


def _make_stage_router(*, next_stage: str):
    def route_after_stage(state: FactoryGraphState) -> str:
        if _last_message_has_tool_calls(state):
            return FACTORY_TOOL_APPROVAL_NODE
        graph_control = state.get("graph_control") or {}
        if graph_control.get("action") == "end":
            return END
        return next_stage

    return route_after_stage


def _route_after_tools(state: FactoryGraphState) -> str:
    current_stage = state.get("current_stage")
    if current_stage not in STAGE_IDS:
        return END
    return current_stage


def _route_after_tool_approval(state: FactoryGraphState) -> str:
    current_stage = state.get("current_stage")
    return route_after_tool_approval(
        state,
        approved=FACTORY_TOOLS_NODE,
        denied=current_stage if current_stage in STAGE_IDS else END,
    )


def _last_message_has_tool_calls(state: FactoryGraphState) -> bool:
    messages = state.get("messages") or []
    if not messages:
        return False
    return bool(getattr(messages[-1], "tool_calls", None))


def initial_factory_graph_state(
    *,
    requirement: str,
    messages,
    force_manufacture: bool = False,
    interaction_mode: str | None = None,
) -> FactoryGraphState:
    return {
        "factory_run_id": uuid.uuid4().hex,
        "requirement": requirement,
        "messages": messages,
        "status": "running",
        "force_manufacture": force_manufacture,
        "interaction_mode": interaction_mode or "",
        "protected_tool_ids": get_factory_protected_tool_ids(),
        "stage_log": [],
        "errors": [],
    }


def _default_checkpointer(enable_interrupts: bool) -> BaseCheckpointSaver | None:
    if not enable_interrupts:
        return None
    return InMemorySaver()
