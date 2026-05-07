from __future__ import annotations

from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.factory_graph.stages.base import run_empty_stage


def run(state: FactoryGraphState) -> dict:
    return run_empty_stage(state, stage_id="capture_requirement")
