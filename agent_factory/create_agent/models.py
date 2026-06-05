from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
import hashlib
import json
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


TODO_FILE = ".factory/todo.json"
ACTION_FILE = ".factory/action.json"
VALIDATION_FILE = ".factory/validation.json"
VALIDATION_STATE_FILE = ".factory/validation_state.json"
RESOURCES_FILE = ".factory/resources.json"
SKILL_GATEWAY_STATE_FILE = ".factory/skill_gateway_state.json"
TEXT_SUMMARY_LIMIT = 240
TODO_TITLE_LIMIT = 160
TODO_COMPLETION_SUMMARY_LIMIT = 220


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

    @model_validator(mode="before")
    @classmethod
    def _normalize_package_validator_details(cls, value: Any) -> Any:
        if not isinstance(value, dict) or value.get("source") != "package_validator":
            return value
        details = value.get("details")
        if not isinstance(details, dict):
            return value
        compact = _compact_issue_details(details)
        payload = dict(value)
        payload["details"] = compact
        return payload

    @field_validator("todo_id")
    @classmethod
    def _clean_todo_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("todo_id must not be empty")
        return cleaned

    @field_validator("title")
    @classmethod
    def _compact_title(cls, value: str) -> str:
        return _compact_text(value, TODO_TITLE_LIMIT)

    @field_validator("acceptance")
    @classmethod
    def _compact_acceptance(cls, value: str) -> str:
        return _compact_text(value, TEXT_SUMMARY_LIMIT)

    def to_digest(self) -> "TodoItemDigest":
        issue_id = ""
        where = ""
        if isinstance(self.details, dict):
            issue_id = str(self.details.get("issue_id") or "")
            where = str(self.details.get("where") or "")
        return TodoItemDigest(
            todo_id=self.todo_id,
            title=_compact_text(self.title, TODO_TITLE_LIMIT),
            kind=self.kind,
            status=self.status,
            required=self.required,
            target_files=self.target_files[:8],
            acceptance=_compact_text(self.acceptance, TEXT_SUMMARY_LIMIT),
            source=self.source,
            issue_id=issue_id,
            where=where,
        )

    def completion_summary(self) -> "TodoCompletionSummary":
        evidence = []
        if isinstance(self.details, dict):
            raw_evidence = self.details.get("evidence")
            if isinstance(raw_evidence, list):
                evidence = [_compact_text(item, TODO_COMPLETION_SUMMARY_LIMIT) for item in raw_evidence[:4]]
        return TodoCompletionSummary(
            todo_id=self.todo_id,
            title=_compact_text(self.title, TODO_TITLE_LIMIT),
            target_files=self.target_files[:8],
            evidence=evidence,
            acceptance=_compact_text(self.acceptance, TEXT_SUMMARY_LIMIT),
        )


class TodoItemDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    todo_id: str
    title: str
    kind: Literal["plan", "write", "verify", "repair", "question"]
    status: TodoStatus
    required: bool = True
    target_files: list[str] = Field(default_factory=list)
    acceptance: str = ""
    source: str = "factory"
    issue_id: str = ""
    where: str = ""


class TodoCompletionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    todo_id: str
    title: str
    target_files: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    acceptance: str = ""


class TodoStatusCount(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: TodoStatus
    count: int


class TodoWorkingSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["create_agent_working_set.v0"] = "create_agent_working_set.v0"
    active_todo: TodoItemDigest | None = None
    items: list[TodoItemDigest] = Field(default_factory=list)
    status_counts: list[TodoStatusCount] = Field(default_factory=list)
    required_remaining: int = 0
    total_items: int = 0


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

    def working_set(self, *, limit: int = 8) -> TodoWorkingSet:
        ordered_pairs = sorted(
            enumerate(self.items),
            key=lambda pair: (
                _todo_priority(pair[1].status),
                0 if pair[1].required else 1,
                pair[0],
            ),
        )
        ordered = [item for _index, item in ordered_pairs]
        selected = ordered[: max(1, limit)]
        active = selected[0].to_digest() if selected else None
        counts = [
            TodoStatusCount(status=status, count=sum(1 for item in self.items if item.status == status))
            for status in TodoStatus
        ]
        return TodoWorkingSet(
            active_todo=active,
            items=[item.to_digest() for item in selected],
            status_counts=counts,
            required_remaining=sum(
                1
                for item in self.items
                if item.required and item.status != TodoStatus.done
            ),
            total_items=len(self.items),
        )

    def upsert_repair_items(self, issues: list["PackageValidationIssue"]) -> "TodoList":
        existing_ids = {item.todo_id for item in self.items}
        items = list(self.items)
        for issue in issues:
            digest = issue.to_digest()
            todo_id = digest.repair_todo_id()
            if todo_id in existing_ids:
                continue
            existing_ids.add(todo_id)
            items.append(
                TodoItem(
                    todo_id=todo_id,
                    title=_compact_text(f"Repair {digest.where}: {digest.summary}", TODO_TITLE_LIMIT),
                    kind="repair",
                    status=TodoStatus.failed_needs_repair,
                    target_files=digest.target_files,
                    acceptance="Package validation passes for this issue.",
                    source="package_validator",
                    details=digest.model_dump(mode="json"),
                )
            )
        return self.model_copy(update={"items": items, "updated_at": datetime.now(UTC).isoformat()})

    def completion_summaries(self, *, limit: int = 6) -> list[TodoCompletionSummary]:
        done_items = [item for item in self.items if item.status == TodoStatus.done]
        return [item.completion_summary() for item in done_items[-max(0, limit):]]


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


class PackageRepairTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_key: str = ""
    target_file: str
    recommended_skill: str = ""
    recommended_resources: list[str] = Field(default_factory=list)


class PackageRepairBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    kind: Literal[
        "manifest_missing",
        "missing_required_contracts",
        "missing_referenced_files",
        "runtime_path_contract_repair",
        "runtime_contract_build",
        "assembly_compile",
        "python_syntax",
        "generic_repair",
    ]
    repair_action: Literal[
        "materialize_base_package",
        "materialize_required_contracts",
        "normalize_runtime_contract_paths",
        "read_skill_resources",
        "repair_files",
        "fix_python_syntax",
    ]
    machine_applicable: bool = False
    target_files: list[str] = Field(default_factory=list)
    targets: list[PackageRepairTarget] = Field(default_factory=list)
    recommended_skill: str = ""
    recommended_resources: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


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
    recommended_skill: str = ""
    recommended_resources: list[str] = Field(default_factory=list)
    repair_bundle: PackageRepairBundle | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    def repair_todo_id(self) -> str:
        return self.to_digest().repair_todo_id()

    def to_digest(self) -> "ValidationIssueDigest":
        raw = json.dumps(
            {
                "where": self.where,
                "path": self.path,
                "target_files": self.target_files,
                "recommended_skill": self.recommended_skill,
                "summary": self.summary,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        issue_id = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return ValidationIssueDigest(
            issue_id=issue_id,
            where=self.where,
            summary=_compact_text(self.summary, TEXT_SUMMARY_LIMIT),
            severity=self.severity,
            path=self.path,
            expected=_compact_text(self.expected, TEXT_SUMMARY_LIMIT),
            actual=_compact_text(self.actual, TEXT_SUMMARY_LIMIT),
            repair_hint=_compact_text(self.repair_hint, TEXT_SUMMARY_LIMIT),
            target_files=self.target_files[:8],
            recommended_skill=self.recommended_skill,
            recommended_resources=self.recommended_resources[:8],
        )


class ValidationIssueDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str
    where: str
    summary: str
    severity: Literal["blocking", "warning", "info"] = "blocking"
    path: str = ""
    expected: str = ""
    actual: str = ""
    repair_hint: str = ""
    target_files: list[str] = Field(default_factory=list)
    recommended_skill: str = ""
    recommended_resources: list[str] = Field(default_factory=list)

    def repair_todo_id(self) -> str:
        return f"repair_{self.issue_id}"


class PackageValidationNextAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["continue", "repair_files", "ask_user", "finalize_ready"] = "continue"
    target_files: list[str] = Field(default_factory=list)
    recommended_skill: str = ""
    recommended_resources: list[str] = Field(default_factory=list)
    repair_bundles: list[PackageRepairBundle] = Field(default_factory=list)


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

    def to_digest(self) -> "PackageValidationDigest":
        return PackageValidationDigest(
            status=self.status,
            package_root=self.package_root,
            validation_scope=self.validation_scope,
            changed_files=self.changed_files[:12],
            cached=self.cached,
            skipped=self.skipped,
            summary=_compact_text(self.summary, TEXT_SUMMARY_LIMIT),
            next_action=self.next_action,
            issues=[issue.to_digest() for issue in self.issues[:8]],
        )


class PackageValidationDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_validation_digest.v0"] = "package_validation_digest.v0"
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
    issues: list[ValidationIssueDigest] = Field(default_factory=list)


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
                acceptance=".factory/todo.json contains concrete system-boundary todos with specific target_files.",
            ),
            TodoItem(
                todo_id="package_manifest",
                title="Materialize package identity and manifest references",
                kind="write",
                acceptance="agent_package.json exists and references only existing package-relative files.",
            ),
            TodoItem(
                todo_id="runtime_contracts",
                title="Materialize RuntimeContracts with actual configuration",
                kind="write",
                acceptance="RuntimeBuildPlanner can build all contracts AND contracts contain non-default configuration matching user requirements.",
            ),
            TodoItem(
                todo_id="assembly_and_patterns",
                title="Materialize assembly with operational logic",
                kind="write",
                acceptance="Pattern has >2 nodes with at least one cognitive/operational node. Assembly bindings are non-empty.",
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
                acceptance="tools_contract declares at least one tool. Package tools (if any) pass import and invocation test.",
            ),
            TodoItem(
                todo_id="validate_agent_package",
                title="Validate the AgentPackage through full_static including semantic check and smoke test",
                kind="verify",
                acceptance="Package passes full_static validation including semantic completeness and runtime smoke test with task_model.",
            ),
        ]
    )


def _todo_priority(status: TodoStatus) -> int:
    return {
        TodoStatus.in_progress: 0,
        TodoStatus.failed_needs_repair: 1,
        TodoStatus.blocked_waiting_user: 2,
        TodoStatus.pending: 3,
        TodoStatus.skipped_by_user: 4,
        TodoStatus.done: 5,
    }[status]


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}…"


def _compact_issue_details(details: dict[str, Any]) -> dict[str, Any]:
    where = str(details.get("where") or "")
    summary = _compact_text(details.get("summary") or details.get("message") or where, TEXT_SUMMARY_LIMIT)
    target_files = details.get("target_files")
    if not isinstance(target_files, list):
        target_files = []
    recommended_resources = details.get("recommended_resources")
    if not isinstance(recommended_resources, list):
        recommended_resources = []
    issue_id = str(details.get("issue_id") or "")
    if not issue_id:
        raw = json.dumps(
            {
                "where": where,
                "path": details.get("path") or "",
                "target_files": target_files,
                "recommended_skill": details.get("recommended_skill") or "",
                "summary": summary,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        issue_id = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return {
        "issue_id": issue_id,
        "where": where,
        "summary": summary,
        "repair_hint": _compact_text(details.get("repair_hint") or "", TEXT_SUMMARY_LIMIT),
        "target_files": [str(item) for item in target_files[:8]],
        "recommended_skill": str(details.get("recommended_skill") or ""),
        "recommended_resources": [str(item) for item in recommended_resources[:8]],
    }
