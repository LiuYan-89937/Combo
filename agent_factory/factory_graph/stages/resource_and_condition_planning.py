from __future__ import annotations

from agent_factory.factory_graph.stage_subgraphs.resource_and_condition_planning import (
    run_resource_and_condition_planning_subgraph,
)
from agent_factory.factory_graph.state import FactoryGraphState


def run(state: FactoryGraphState) -> dict:
    return run_resource_and_condition_planning_subgraph(state)
