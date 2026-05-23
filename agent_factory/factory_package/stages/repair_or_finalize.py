from __future__ import annotations

from agent_factory.factory_package.stages.base import run_placeholder_stage
from agent_factory.factory_package.state import FactoryPackageState


def run(state: FactoryPackageState) -> dict:
    return run_placeholder_stage(state, stage_id="repair_or_finalize")
