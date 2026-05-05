from __future__ import annotations

import json
import uuid
from pathlib import Path

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


class UpgradeAgentService:
    def create_request(
        self,
        agent_name: str,
        *,
        prompt: str,
        proposed_intent: str = "user_requested_upgrade",
        source_path: Path | None = None,
    ) -> UpgradeRequest:
        request = UpgradeRequest(
            agent_name=agent_name,
            proposed_intent=proposed_intent,
            prompt=prompt,
            source_path=source_path,
        )
        workspace = FactoryWorkspace.discover()
        workspace.ensure()
        path = workspace.workspace_path / "upgrades" / f"{request.request_id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        YAML().dump(json.loads(request.model_dump_json()), path.open("w", encoding="utf-8"))
        return request
