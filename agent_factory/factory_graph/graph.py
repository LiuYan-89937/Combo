from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent_factory.factory_graph.constants import STAGE_IDS
from agent_factory.factory_graph.stages import STAGE_RUNNERS
from agent_factory.factory_graph.state import FactoryGraphState


def build_factory_graph(*, stop_after_stage: str | None = None):
    if stop_after_stage is not None and stop_after_stage not in STAGE_IDS:
        raise ValueError(f"Unknown factory stage: {stop_after_stage}")

    graph = StateGraph(FactoryGraphState)
    for stage_id in STAGE_IDS:
        graph.add_node(stage_id, STAGE_RUNNERS[stage_id])

    graph.add_edge(START, STAGE_IDS[0])
    for current_stage, next_stage in zip(STAGE_IDS, STAGE_IDS[1:]):
        if current_stage == stop_after_stage:
            graph.add_edge(current_stage, END)
        else:
            graph.add_edge(current_stage, next_stage)
    graph.add_edge(STAGE_IDS[-1], END)
    return graph.compile()
