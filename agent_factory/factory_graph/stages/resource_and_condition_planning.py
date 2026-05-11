from __future__ import annotations

from agent_factory.factory_graph.stage_subgraphs.resource_preparation import (
    run_resource_preparation_subgraph,
)
from agent_factory.factory_graph.state import FactoryGraphState


def run(state: FactoryGraphState) -> dict:
    return run_resource_preparation_subgraph(state)
