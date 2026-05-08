from __future__ import annotations

from agent_factory.factory_graph.stages.base import run_empty_stage
from agent_factory.factory_graph.state import FactoryGraphState


def run(state: FactoryGraphState) -> dict:
    return run_empty_stage(state, stage_id="node_strategy_planning")
