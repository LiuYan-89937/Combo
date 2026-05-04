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
    active_agent_target: str | None = None
    active_agent_path: Path | None = None
    active_session_id: str = "default"
    pending_tool_approval: dict | None = None

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

    @property
    def in_agent_chat(self) -> bool:
        return bool(self.active_agent_target)

    def enter_agent_chat(
        self,
        *,
        target: str,
        path: Path | None = None,
        session_id: str = "default",
    ) -> None:
        self.active_agent_target = target
        self.active_agent_path = path
        self.active_session_id = session_id or "default"
        self.pending_tool_approval = None
        if path is not None:
            self.selected_agent_path = path

    def exit_agent_chat(self) -> None:
        self.active_agent_target = None
        self.active_agent_path = None
        self.active_session_id = "default"
        self.pending_tool_approval = None

    def capture_tool_approval(
        self,
        *,
        user_input: str,
        tool_call_id: str,
        tool_id: str,
    ) -> None:
        self.pending_tool_approval = {
            "user_input": user_input,
            "tool_call_id": tool_call_id,
            "tool_id": tool_id,
        }

    def clear_tool_approval(self) -> None:
        self.pending_tool_approval = None
