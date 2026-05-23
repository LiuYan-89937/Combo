from __future__ import annotations

from agent_factory.factory_package.stage_subgraphs.package_generation import run_package_generation_subgraph
from agent_factory.factory_package.state import FactoryPackageState


def run(state: FactoryPackageState) -> dict:
    return run_package_generation_subgraph(state)
