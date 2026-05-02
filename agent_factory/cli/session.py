from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.core import sanitize_requirement_text


class ShellSession(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    pending_requirement: str | None = None
    selected_agent_path: Path | None = None
    draft_paths: list[Path] = Field(default_factory=list)

    def capture_requirement(self, text: str) -> None:
        stripped = sanitize_requirement_text(text)
        if stripped:
            self.pending_requirement = stripped
