from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent_factory.factory_runtime.production.nodes import FACTORY_STAGE_SEQUENCE, FactoryProductionNodes
from agent_factory.factory_runtime.production.routes import route_after_stage
from agent_factory.factory_runtime.production.state import FactoryProductionStateDict


def build_factory_production_graph(nodes: FactoryProductionNodes):
    graph = StateGraph(FactoryProductionStateDict)
    for stage in FACTORY_STAGE_SEQUENCE:
        graph.add_node(stage, nodes.guarded(stage))

    graph.add_edge(START, FACTORY_STAGE_SEQUENCE[0])

    for index, stage in enumerate(FACTORY_STAGE_SEQUENCE[:-1]):
        next_stage = FACTORY_STAGE_SEQUENCE[index + 1]
        graph.add_conditional_edges(
            stage,
            route_after_stage,
            {
                "continue": next_stage,
                "end": END,
            },
        )

    graph.add_edge(FACTORY_STAGE_SEQUENCE[-1], END)
    return graph.compile()
