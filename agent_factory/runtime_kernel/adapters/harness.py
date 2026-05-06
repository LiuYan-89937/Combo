from __future__ import annotations

from typing import Any, Protocol


class HarnessAdapter(Protocol):
    def prepare_fixture(self, fixture: Any) -> Any:
        ...
