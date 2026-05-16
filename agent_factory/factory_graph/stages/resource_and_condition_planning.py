from __future__ import annotations

import json
from pathlib import Path

from agent_factory.factory_graph.constants import EMPTY_STAGE_MESSAGE
from agent_factory.factory_graph.state import FactoryGraphState


RESOURCE_FILE_VERSION = "factory_resources.v0"
RESOURCE_ROOT = ".agentfactory/resources"
STAGE_ID = "resource_and_condition_planning"


def run(state: FactoryGraphState) -> dict:
    factory_run_id = str(state.get("factory_run_id") or "default")
    resource_file_path = _resource_file_path(factory_run_id)
    resources: dict[str, object] = {}
    resource_file_path.parent.mkdir(parents=True, exist_ok=True)
    resource_file_path.write_text(
        json.dumps(
            {
                "version": RESOURCE_FILE_VERSION,
                "resources": resources,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "current_stage": STAGE_ID,
        "status": "running",
        "resource_file_path": str(resource_file_path),
        "resource_condition_plan": {
            "status": "pending_implementation",
            "requirements": [],
            "check_results": [],
            "user_inputs": [],
            "resource_draft": {},
            "resources": resources,
            "resource_file_path": str(resource_file_path),
        },
        "stage_log": [
            {
                "stage_id": STAGE_ID,
                "status": "pending_implementation",
                "message": EMPTY_STAGE_MESSAGE,
            }
        ],
    }


def _resource_file_path(factory_run_id: str) -> Path:
    return Path(RESOURCE_ROOT) / factory_run_id / "factory_resources.json"
