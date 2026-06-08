from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from agent_factory.create_agent.models import SYSTEM_STATE_FILE, SystemManufacturingState, SystemStage, initial_system_manufacturing_state


CREATE_AGENT_STAGE_CONTEXT_RESOURCE = "create_agent_stage_context"


@dataclass(frozen=True, slots=True)
class CreateAgentStageContext:
    workspace_root: Path

    @classmethod
    def from_workspace_root(cls, root: str | Path) -> "CreateAgentStageContext":
        return cls(Path(root).expanduser().resolve())

    @property
    def system_state_path(self) -> Path:
        return self.workspace_root / SYSTEM_STATE_FILE

    def read_state(self) -> SystemManufacturingState:
        if not self.system_state_path.exists():
            return initial_system_manufacturing_state()
        return SystemManufacturingState.model_validate_json(self.system_state_path.read_text(encoding="utf-8"))

    def write_state(self, state: SystemManufacturingState) -> None:
        self.system_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.system_state_path.write_text(
            json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def active_stage(self) -> SystemStage | None:
        return self.read_state().active_stage()

    def assert_active_system(self, requested_system_id: str) -> SystemStage:
        active = self.active_stage()
        if active is None:
            raise ValueError("no active system")
        requested = str(requested_system_id or "").strip()
        if requested and requested != active.system_id:
            raise ValueError(
                f"requested system {requested!r} is not active; active system is {active.system_id!r}. "
                "All create-agent tools must use the active system from the unified stage context."
            )
        return active

    def file_owners(self) -> dict[str, str]:
        owners: dict[str, str] = {}
        for stage in self.read_state().stages:
            system_id = str(stage.system_id or "").strip()
            if not system_id:
                continue
            for item in stage.owned_files:
                cleaned = str(item or "").strip()
                if cleaned:
                    owners[cleaned] = system_id
        return owners

    def active_owned_files(self) -> list[str]:
        active = self.active_stage()
        return list(active.owned_files) if active else []


def stage_context_payload(workspace_root: str | Path) -> dict[str, str]:
    return {"workspace_root": str(Path(workspace_root).expanduser().resolve())}


def stage_context_from_resources(resources: dict[str, Any]) -> CreateAgentStageContext | None:
    raw = resources.get(CREATE_AGENT_STAGE_CONTEXT_RESOURCE)
    if raw is None:
        filesystem = resources.get("filesystem")
        if isinstance(filesystem, dict):
            raw = filesystem.get(CREATE_AGENT_STAGE_CONTEXT_RESOURCE)
    if isinstance(raw, dict) and isinstance(raw.get("workspace_root"), str):
        return CreateAgentStageContext.from_workspace_root(raw["workspace_root"])
    if isinstance(raw, str) and raw.strip():
        return CreateAgentStageContext.from_workspace_root(raw)
    return None
