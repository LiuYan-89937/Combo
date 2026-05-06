from __future__ import annotations

from typing import Literal

from agent_factory.factory_runtime.production.state import FactoryProductionStateDict


def route_after_stage(
    state: FactoryProductionStateDict,
) -> Literal["continue", "end"]:
    status = state.get("status")
    if status in {"paused", "failed"}:
        return "end"
    return "continue"
