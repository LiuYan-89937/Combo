from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from agent_factory.create_agent.models import (
    ACTION_FILE,
    RESOURCES_FILE,
    SKILL_GATEWAY_STATE_FILE,
    TODO_FILE,
    VALIDATION_FILE,
    VALIDATION_STATE_FILE,
    CreateAgentAction,
    PackageValidationReport,
    PackageValidationState,
    TodoList,
    initial_todo_list,
)
from agent_factory.create_agent.scaffold import ensure_base_package
from agent_factory.tooling.builtins.resource_set.resource_set import RESOURCE_SET_STORE_KEY, ResourceSetStore
from agent_factory.paths import factory_artifact_path
from agent_factory.tooling.output_store import ToolOutputStore


ModelT = TypeVar("ModelT", bound=BaseModel)


class CreateAgentWorkspace:
    def __init__(self, root: str | Path, *, resource_set_store: ResourceSetStore | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self._resource_set_store = resource_set_store

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
        ensure_base_package(self.root, request_text=request_path.read_text(encoding="utf-8"))

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

    @property
    def skill_gateway_state_path(self) -> Path:
        return self.root / SKILL_GATEWAY_STATE_FILE

    @property
    def request_path(self) -> Path:
        return self.factory_dir / "request.txt"

    @property
    def tool_outputs_path(self) -> Path:
        return self.factory_dir / "tool_outputs"

    def read_todo(self) -> TodoList:
        if not self.todo_path.exists():
            return initial_todo_list()
        return TodoList.model_validate_json(self.todo_path.read_text(encoding="utf-8"))

    def write_todo(self, todo: TodoList) -> None:
        self._write_json(self.todo_path, todo.model_dump(mode="json"))

    def read_action(self) -> CreateAgentAction:
        return _read_managed_model(
            self.action_path,
            CreateAgentAction,
            missing=CreateAgentAction(),
            owner_tool="create_agent_control",
        )

    def write_action(self, action: CreateAgentAction) -> None:
        self._write_json(self.action_path, action.model_dump(mode="json"))

    def write_validation(self, report: PackageValidationReport) -> None:
        self._write_json(self.validation_path, report.model_dump(mode="json"))

    def read_validation(self) -> PackageValidationReport | None:
        return _read_managed_model(
            self.validation_path,
            PackageValidationReport,
            missing=None,
            owner_tool="create_agent_validate",
        )

    def read_validation_state(self) -> PackageValidationState | None:
        return _read_managed_model(
            self.validation_state_path,
            PackageValidationState,
            missing=None,
            owner_tool="create_agent_validate",
        )

    def write_validation_state(self, state: PackageValidationState) -> None:
        self._write_json(self.validation_state_path, state.model_dump(mode="json"))

    def package_manifest_path(self) -> Path:
        return self.root / "agent_package.json"

    def context_summary(self, *, resource_set_store: ResourceSetStore | None = None) -> str:
        effective_store = resource_set_store or self._resource_set_store
        todo = self.read_todo()
        action = self.read_action()
        validation = self.read_validation()
        working_set = todo.working_set()
        request_text = self._read_text_snippet(self.request_path, limit=360)
        lines = [
            f"Workspace: {self.root}",
            f"Original request: {request_text}" if request_text else "Original request: unavailable",
            f"Todo file: {TODO_FILE} (managed by create_agent_todo; do not edit directly)",
            f"Action file: {ACTION_FILE} (managed by create_agent_control; do not edit directly)",
            f"Resources file: {RESOURCES_FILE}",
            f"Validation file: {VALIDATION_FILE}",
            f"Required remaining todos: {working_set.required_remaining}/{working_set.total_items}",
            "Active todo working set:",
        ]
        for item in working_set.items:
            lines.append(f"- {item.todo_id}: {item.status.value} | {item.title}")
        completed = todo.completion_summaries()
        if completed:
            lines.append("Completed todo summaries:")
            for item in completed:
                evidence = "; ".join(item.evidence[:3]) if item.evidence else item.acceptance
                files = ", ".join(item.target_files[:4]) if item.target_files else "no specific files"
                lines.append(f"- {item.todo_id}: {item.title} | files={files} | {evidence}")
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
        # Resource set: paths already explored in this session
        if effective_store is not None and effective_store.size() > 0:
            explored_paths = effective_store.list_paths()
            lines.append(f"Explored resource paths ({len(explored_paths)} total, do NOT re-read these):")
            for path in explored_paths[:20]:
                lines.append(f"- {path}")
            if len(explored_paths) > 20:
                lines.append(f"  ... and {len(explored_paths) - 20} more (use resource_set list to view all)")
        output_refs = ToolOutputStore(self.tool_outputs_path).list_outputs(limit=8)
        if output_refs:
            lines.append("Available tool outputs:")
            for ref in output_refs:
                lines.append(
                    f"- {ref['id']}: tool={ref['tool_id']} | chars={ref['size_chars']} | created={ref['created_at']}"
                )
        else:
            lines.append("Available tool outputs: none. Do not call tool_output read unless an output_id is listed.")
        return "\n".join(lines)

    def _read_text_snippet(self, path: Path, *, limit: int) -> str:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        return " ".join(text.split())[:limit]

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        _assert_inside(self.root, path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_managed_model(path: Path, model: type[ModelT], *, missing: ModelT | None, owner_tool: str) -> ModelT | None:
    if not path.exists():
        return missing
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(
            f"invalid managed create-agent file: {path}. Regenerate it through {owner_tool}; "
            "direct edits and older structures are not accepted."
        ) from exc


def _assert_inside(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes create-agent workspace: {path}") from exc
