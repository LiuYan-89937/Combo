from __future__ import annotations

from typing import Any

from agent_factory.factory_package.constants import EMPTY_STAGE_MESSAGE
from agent_factory.factory_package.state import FactoryPackageState


def placeholder_stage_patch(stage_id: str) -> dict[str, Any]:
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


def run_placeholder_stage(state: FactoryPackageState, *, stage_id: str) -> dict[str, Any]:
    return placeholder_stage_patch(stage_id)
