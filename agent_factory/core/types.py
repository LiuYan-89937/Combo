from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel


class JsonDumpMixin(BaseModel):
    """Small JSON helper for CLI-safe serialization."""

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_json(self) -> str:
        return json.dumps(self.to_json_dict(), ensure_ascii=False)
