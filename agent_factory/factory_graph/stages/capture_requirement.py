from __future__ import annotations

from agent_factory.factory_graph.stage_subgraphs.capture_requirement import (
    run_capture_requirement_subgraph,
)
from agent_factory.factory_graph.state import FactoryGraphState


def run(state: FactoryGraphState) -> dict:
    return run_capture_requirement_subgraph(state)
