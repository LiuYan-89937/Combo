from __future__ import annotations

from typing import Any, Protocol


class MemoryEngineAdapter(Protocol):
    def recall(self, *, state: Any, binding: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...

    def write(self, *, state: Any, binding: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...
