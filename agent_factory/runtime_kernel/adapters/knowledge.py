from __future__ import annotations

from typing import Any, Protocol


class KnowledgeEngineAdapter(Protocol):
    def retrieve(self, *, state: Any, binding: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...
