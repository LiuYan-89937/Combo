from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
import hashlib
import json
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


TODO_FILE = ".factory/todo.json"
ACTION_FILE = ".factory/action.json"
VALIDATION_FILE = ".factory/validation.json"
VALIDATION_STATE_FILE = ".factory/validation_state.json"
RESOURCES_FILE = ".factory/resources.json"


class TodoStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    blocked_waiting_user = "blocked_waiting_user"
    failed_needs_repair = "failed_needs_repair"
    done = "done"
    skipped_by_user = "skipped_by_user"


class TodoItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    todo_id: str = Field(default_factory=lambda: f"todo_{uuid4().hex[:12]}")
    title: str
    kind: Literal["plan", "write", "verify", "repair", "question"] = "write"
    status: TodoStatus = TodoStatus.pending
    required: bool = True
    target_files: list[str] = Field(default_factory=list)
    acceptance: str = ""
    source: str = "factory"
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("todo_id")
    @classmethod
    def _clean_todo_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("todo_id must not be empty")
        return cleaned


class TodoList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["create_agent_todo.v0"] = "create_agent_todo.v0"
    items: list[TodoItem] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def all_required_done(self) -> bool:
        return all(
            item.status == TodoStatus.done
            for item in self.items
            if item.required
        )

    def upsert_repair_items(self, issues: list["PackageValidationIssue"]) -> "TodoList":
        existing_ids = {item.todo_id for item in self.items}
        items = list(self.items)
        for issue in issues:
            todo_id = issue.repair_todo_id()
            if todo_id in existing_ids:
                continue
            existing_ids.add(todo_id)
            items.append(
                TodoItem(
                    todo_id=todo_id,
                    title=f"Repair package validation issue: {issue.summary}",
                    kind="repair",
                    status=TodoStatus.failed_needs_repair,
                    target_files=issue.target_files,
                    acceptance="Package validation passes for this issue.",
                    source="package_validator",
                    details=issue.model_dump(mode="json"),
                )
            )
        return self.model_copy(update={"items": items, "updated_at": datetime.now(UTC).isoformat()})


class ResourceFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: Any = None
    secret: bool = False
    source: Literal["user", "tool", "mcp", "skill", "default", "system"] = "user"
    confidence: float = 1.0
    evidence_refs: list[str] = Field(default_factory=list)


class CreateAgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["continue", "ask_user", "finalize"] = "continue"
    message: str = ""
    resource_facts: list[ResourceFact] = Field(default_factory=list)


class CreateAgentIntentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["manufacture_agent", "workspace_assist", "chat"]
    rationale: str = ""


class PackageValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    where: str
    summary: str
    message: str
    severity: Literal["blocking", "warning", "info"] = "blocking"
    path: str = ""
    expected: str = ""
    actual: str = ""
    repair_hint: str = ""
    target_files: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)

    def repair_todo_id(self) -> str:
        raw = json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return f"repair_{digest}"


class PackageValidationNextAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["continue", "repair_files", "ask_user", "finalize_ready"] = "continue"
    target_files: list[str] = Field(default_factory=list)
    recommended_skill: str = ""


class PackageValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_validation_report.v0"] = "package_validation_report.v0"
    status: Literal["passed", "failed"] = "failed"
    package_root: str
    validation_scope: Literal[
        "workspace_hygiene",
        "package_shape",
        "runtime_contract_build",
        "assembly_compile",
        "python_syntax",
        "full_static",
        "unchanged",
    ] = "full_static"
    changed_files: list[str] = Field(default_factory=list)
    cached: bool = False
    skipped: bool = False
    summary: str = ""
    next_action: PackageValidationNextAction = Field(default_factory=PackageValidationNextAction)
    issues: list[PackageValidationIssue] = Field(default_factory=list)


class PackageValidationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_validation_state.v0"] = "package_validation_state.v0"
    package_fingerprint: dict[str, str] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def initial_todo_list() -> TodoList:
    return TodoList(
        items=[
            TodoItem(
                todo_id="todo_control_plan",
                title="Create a RuntimeKernel-verifiable manufacturing plan",
                kind="plan",
                acceptance=".factory/todo.json contains concrete system-boundary todos.",
            ),
            TodoItem(
                todo_id="package_manifest",
                title="Materialize package identity and manifest references",
                kind="write",
                acceptance="agent_package.json exists and references only existing package-relative files.",
            ),
            TodoItem(
                todo_id="runtime_contracts",
                title="Materialize RuntimeContracts used by the package",
                kind="write",
                acceptance="RuntimeBuildPlanner can build all referenced contracts.",
            ),
            TodoItem(
                todo_id="assembly_and_patterns",
                title="Materialize assembly and executable graph patterns",
                kind="write",
                acceptance="AgentAssemblyCompiler can compile the assembly.",
            ),
            TodoItem(
                todo_id="state_resources_render",
                title="Materialize state, resources, and render surfaces",
                kind="write",
                acceptance="State, resources, and render manifests are loadable and package-relative.",
            ),
            TodoItem(
                todo_id="tools_nodes_extensions",
                title="Resolve tools, extensions, package tools, and package nodes",
                kind="write",
                acceptance="Required capabilities are inherited or materialized without duplicate tools or hardcoded resources.",
            ),
            TodoItem(
                todo_id="validate_agent_package",
                title="Validate the AgentPackage through the package validator",
                kind="verify",
                acceptance="Package validation passes.",
            ),
        ]
    )
