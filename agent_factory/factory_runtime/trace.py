from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_factory.core import FactoryEvent
from agent_factory.factory_runtime.redaction import redact_secrets


class FactoryTraceStore:
    def __init__(
        self,
        path: str | Path,
        *,
        enabled: bool = True,
        redact: bool = True,
    ) -> None:
        self.path = Path(path)
        self.enabled = enabled
        self.redact = redact

    def append_event(self, event: FactoryEvent) -> None:
        if not self.enabled:
            return
        data = event.model_dump(mode="json")
        if self.redact:
            data = redact_secrets(data)
        self._append(data)

    def list_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events

    def _append(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False) + "\n")
