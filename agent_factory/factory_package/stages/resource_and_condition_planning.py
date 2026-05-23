from __future__ import annotations

from agent_factory.factory_package.stage_subgraphs.resource_and_condition_planning import (
    run_resource_and_condition_planning_subgraph,
)
from agent_factory.factory_package.state import FactoryPackageState


def run(state: FactoryPackageState) -> dict:
    return run_resource_and_condition_planning_subgraph(state)
