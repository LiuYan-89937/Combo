from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agent_factory.create_agent.models import (
    ACTION_FILE,
    RESOURCES_FILE,
    TODO_FILE,
    VALIDATION_FILE,
    VALIDATION_STATE_FILE,
    CreateAgentAction,
    PackageValidationReport,
    PackageValidationState,
    TodoList,
    initial_todo_list,
)
from agent_factory.paths import factory_artifact_path


class CreateAgentWorkspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()

    @classmethod
    def for_session(cls, session_id: str) -> "CreateAgentWorkspace":
        safe_session_id = "".join(char for char in session_id if char.isalnum() or char in {"-", "_"})[:64]
        if not safe_session_id:
            raise ValueError("create-agent session id must not be empty")
        return cls(factory_artifact_path("create_agent_workspaces", safe_session_id))

    def initialize(self, *, user_input: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.factory_dir.mkdir(parents=True, exist_ok=True)
        if not self.todo_path.exists():
            self.write_todo(initial_todo_list())
        if not self.action_path.exists():
            self.write_action(CreateAgentAction())
        if not self.resources_path.exists():
            self._write_json(self.resources_path, {"version": "resource_facts.v0", "facts": []})
        request_path = self.factory_dir / "request.txt"
        if not request_path.exists():
            request_path.write_text(user_input, encoding="utf-8")

    @property
    def factory_dir(self) -> Path:
        return self.root / ".factory"

    @property
    def todo_path(self) -> Path:
        return self.root / TODO_FILE

    @property
    def action_path(self) -> Path:
        return self.root / ACTION_FILE

    @property
    def validation_path(self) -> Path:
        return self.root / VALIDATION_FILE

    @property
    def validation_state_path(self) -> Path:
        return self.root / VALIDATION_STATE_FILE

    @property
    def resources_path(self) -> Path:
        return self.root / RESOURCES_FILE

    def read_todo(self) -> TodoList:
        if not self.todo_path.exists():
            return initial_todo_list()
        return TodoList.model_validate_json(self.todo_path.read_text(encoding="utf-8"))

    def write_todo(self, todo: TodoList) -> None:
        self._write_json(self.todo_path, todo.model_dump(mode="json"))

    def read_action(self) -> CreateAgentAction:
        if not self.action_path.exists():
            return CreateAgentAction()
        try:
            return CreateAgentAction.model_validate_json(self.action_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValidationError):
            return CreateAgentAction()

    def write_action(self, action: CreateAgentAction) -> None:
        self._write_json(self.action_path, action.model_dump(mode="json"))

    def write_validation(self, report: PackageValidationReport) -> None:
        self._write_json(self.validation_path, report.model_dump(mode="json"))

    def read_validation(self) -> PackageValidationReport | None:
        if not self.validation_path.exists():
            return None
        try:
            return PackageValidationReport.model_validate_json(self.validation_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValidationError):
            return None

    def read_validation_state(self) -> PackageValidationState | None:
        if not self.validation_state_path.exists():
            return None
        try:
            return PackageValidationState.model_validate_json(self.validation_state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValidationError):
            return None

    def write_validation_state(self, state: PackageValidationState) -> None:
        self._write_json(self.validation_state_path, state.model_dump(mode="json"))

    def package_manifest_path(self) -> Path:
        return self.root / "agent_package.json"

    def context_summary(self) -> str:
        todo = self.read_todo()
        action = self.read_action()
        validation = self.read_validation()
        working_set = todo.working_set()
        lines = [
            f"Workspace: {self.root}",
            f"Todo file: {TODO_FILE} (managed by create_agent_todo; do not edit directly)",
            f"Action file: {ACTION_FILE} (managed by create_agent_control; do not edit directly)",
            f"Resources file: {RESOURCES_FILE}",
            f"Validation file: {VALIDATION_FILE}",
            f"Required remaining todos: {working_set.required_remaining}/{working_set.total_items}",
            "Active todo working set:",
        ]
        for item in working_set.items:
            lines.append(f"- {item.todo_id}: {item.status.value} | {item.title}")
        lines.append(f"Current action: {action.action} {action.message}".strip())
        if validation:
            digest = validation.to_digest()
            lines.append(
                "Latest validation digest: "
                f"{digest.status} | scope={digest.validation_scope} | cached={digest.cached} | {digest.summary}"
            )
            for issue in digest.issues[:3]:
                lines.append(
                    f"- issue {issue.issue_id}: {issue.where} | files={issue.target_files} | {issue.repair_hint}"
                )
        return "\n".join(lines)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        _assert_inside(self.root, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _assert_inside(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes create-agent workspace: {path}") from exc
