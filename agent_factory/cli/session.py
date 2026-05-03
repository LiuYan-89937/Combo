from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.core import sanitize_requirement_text


class ShellSession(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    pending_requirement: str | None = None
    pending_clarification_questions: list[str] = Field(default_factory=list)
    pending_clarification_options: list[dict] = Field(default_factory=list)
    selected_agent_path: Path | None = None
    draft_paths: list[Path] = Field(default_factory=list)

    def capture_requirement(self, text: str) -> None:
        stripped = sanitize_requirement_text(text)
        if not stripped:
            return
        if self.pending_requirement and self.pending_clarification_questions:
            self.pending_requirement = sanitize_requirement_text(
                f"{self.pending_requirement}\n\n用户补充信息：\n{stripped}"
            )
            self.clear_pending_clarification()
            return
        self.pending_requirement = stripped

    def capture_clarification(
        self,
        *,
        questions: list[str],
        options: list[dict],
    ) -> None:
        self.pending_clarification_questions = [question for question in questions if question.strip()]
        self.pending_clarification_options = list(options)

    def clear_pending_clarification(self) -> None:
        self.pending_clarification_questions = []
        self.pending_clarification_options = []

    def clear_pending_requirement(self) -> None:
        self.pending_requirement = None
        self.clear_pending_clarification()
