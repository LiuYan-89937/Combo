from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime.redaction import redact_secrets


class FactoryMemoryRecord(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    type: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FactoryMemoryStore:
    def __init__(self, path: str | Path, *, enabled: bool = True) -> None:
        self.path = Path(path)
        self.enabled = enabled

    def append(self, record: FactoryMemoryRecord) -> None:
        if not self.enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = record.model_dump(mode="json")
        data["payload"] = redact_secrets(data.get("payload", {}))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False) + "\n")

    def list_recent(self, limit: int = 20) -> list[FactoryMemoryRecord]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        records: list[FactoryMemoryRecord] = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            records.append(FactoryMemoryRecord.model_validate(json.loads(line)))
        return records
