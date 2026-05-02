from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime import FactoryWorkspace


class ApprovalRecord(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1"
    kind: str = "ApprovalRecord"
    approval_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    patch_plan: Path | None = None
    change_id: str
    actor: str
    decision: Literal["approved", "rejected"] = "approved"
    reason: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApprovalService:
    def create(
        self,
        *,
        change_id: str,
        actor: str,
        patch_plan: Path | None = None,
        decision: Literal["approved", "rejected"] = "approved",
        reason: str | None = None,
    ) -> ApprovalRecord:
        record = ApprovalRecord(
            patch_plan=patch_plan,
            change_id=change_id,
            actor=actor,
            decision=decision,
            reason=reason,
        )
        workspace = FactoryWorkspace.discover()
        workspace.ensure()
        path = workspace.workspace_path / "approvals" / f"{record.approval_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        return record

    def list(self) -> list[ApprovalRecord]:
        workspace = FactoryWorkspace.discover()
        workspace.ensure()
        root = workspace.workspace_path / "approvals"
        records: list[ApprovalRecord] = []
        for path in sorted(root.glob("*.json")) if root.exists() else []:
            records.append(ApprovalRecord.model_validate_json(path.read_text(encoding="utf-8")))
        return records

    def show(self, approval_id: str) -> ApprovalRecord | None:
        for record in self.list():
            if record.approval_id == approval_id:
                return record
        return None
