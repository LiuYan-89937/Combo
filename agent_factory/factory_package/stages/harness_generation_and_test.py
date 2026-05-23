from __future__ import annotations

from agent_factory.factory_package.stage_subgraphs.harness_generation_and_test import (
    run_harness_generation_and_test_subgraph,
)
from agent_factory.factory_package.state import FactoryPackageState


def run(state: FactoryPackageState) -> dict:
    return run_harness_generation_and_test_subgraph(state)
