from __future__ import annotations

from agent_factory.factory_graph.stage_subgraphs.harness_generation_and_test import (
    run_harness_generation_and_test_subgraph,
)
from agent_factory.factory_graph.state import FactoryGraphState


def run(state: FactoryGraphState) -> dict:
    return run_harness_generation_and_test_subgraph(state)
