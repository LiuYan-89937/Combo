from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field
from ruamel.yaml import YAML

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime import FactoryWorkspace


class UpgradeRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1"
    kind: str = "UpgradeRequest"
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    agent_name: str
    reason: str = "unknown_intent"
    proposed_intent: str
    prompt: str
    source_path: Path | None = None
    target_version: str | None = None
    status: Literal["requested", "planned", "applied", "released", "rejected"] = "requested"
    patch_plan_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UpgradeAgentService:
    def create_request(
        self,
        agent_name: str,
        *,
        prompt: str,
        proposed_intent: str = "user_requested_upgrade",
        source_path: Path | None = None,
        target_version: str | None = None,
    ) -> UpgradeRequest:
        request = UpgradeRequest(
            agent_name=agent_name,
            proposed_intent=proposed_intent,
            prompt=prompt,
            source_path=source_path,
            target_version=target_version,
        )
        self.write_request(request)
        return request

    def mark_planned(self, request: UpgradeRequest, *, patch_plan_id: str) -> UpgradeRequest:
        updated = request.model_copy(
            update={
                "status": "planned",
                "patch_plan_id": patch_plan_id,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.write_request(updated)
        return updated

    def write_request(self, request: UpgradeRequest) -> Path:
        workspace = FactoryWorkspace.discover()
        workspace.ensure()
        path = workspace.workspace_path / "upgrades" / f"{request.request_id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        YAML().dump(json.loads(request.model_dump_json()), path.open("w", encoding="utf-8"))
        return path
