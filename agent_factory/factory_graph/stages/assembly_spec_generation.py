from __future__ import annotations

from agent_factory.factory_graph.stage_subgraphs.assembly_spec_generation import (
    run_assembly_spec_generation_subgraph,
)
from agent_factory.factory_graph.state import FactoryGraphState


def run(state: FactoryGraphState) -> dict:
    return run_assembly_spec_generation_subgraph(state)
