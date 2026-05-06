from __future__ import annotations

from typing import Any

from agent_factory.factory_graph.constants import EMPTY_STAGE_MESSAGE
from agent_factory.factory_graph.state import FactoryGraphState


def empty_stage_patch(stage_id: str) -> dict[str, Any]:
    return {
        "current_stage": stage_id,
        "stage_log": [
            {
                "stage_id": stage_id,
                "status": "pending_implementation",
                "message": EMPTY_STAGE_MESSAGE,
            }
        ],
    }


def run_empty_stage(state: FactoryGraphState, *, stage_id: str) -> dict[str, Any]:
    return empty_stage_patch(stage_id)
