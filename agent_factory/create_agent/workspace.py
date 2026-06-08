from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from agent_factory.create_agent.models import (
    ACTION_FILE,
    RESOURCES_FILE,
    SKILL_GATEWAY_STATE_FILE,
    SYSTEM_STATE_FILE,
    VALIDATION_FILE,
    VALIDATION_STATE_FILE,
    CreateAgentAction,
    PackageValidationReport,
    PackageValidationState,
    SystemManufacturingState,
    initial_system_manufacturing_state,
)
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
        if not self.system_state_path.exists():
            self.write_system_state(initial_system_manufacturing_state())
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
    def system_state_path(self) -> Path:
        return self.root / SYSTEM_STATE_FILE

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
    def manufacturing_trace_path(self) -> Path:
        return self.factory_dir / "manufacturing_trace.json"

    @property
    def tool_outputs_path(self) -> Path:
        return self.factory_dir / "tool_outputs"

    def read_system_state(self) -> SystemManufacturingState:
        if not self.system_state_path.exists():
            return initial_system_manufacturing_state()
        return SystemManufacturingState.model_validate_json(self.system_state_path.read_text(encoding="utf-8"))

    def write_system_state(self, state: SystemManufacturingState) -> None:
        self._write_json(self.system_state_path, state.model_dump(mode="json"))

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
            owner_tool="the internal create-agent validation gate",
        )

    def read_validation_state(self) -> PackageValidationState | None:
        return _read_managed_model(
            self.validation_state_path,
            PackageValidationState,
            missing=None,
            owner_tool="the internal create-agent validation gate",
        )

    def write_validation_state(self, state: PackageValidationState) -> None:
        self._write_json(self.validation_state_path, state.model_dump(mode="json"))

    def reset_manufacturing_trace(self, *, session_id: str, request_id: str, graph_id: str) -> None:
        self._write_json(
            self.manufacturing_trace_path,
            {
                "version": "create_agent_manufacturing_trace.v0",
                "session_id": session_id,
                "request_id": request_id,
                "graph_id": graph_id,
                "workspace_path": str(self.root),
                "created_at": datetime.now(UTC).isoformat(),
                "records": [],
            },
        )

    def append_manufacturing_trace_record(self, record: dict[str, Any]) -> None:
        payload = _read_json_object(self.manufacturing_trace_path)
        if payload.get("version") != "create_agent_manufacturing_trace.v0":
            payload = {
                "version": "create_agent_manufacturing_trace.v0",
                "workspace_path": str(self.root),
                "created_at": datetime.now(UTC).isoformat(),
                "records": [],
            }
        records = payload.get("records")
        if not isinstance(records, list):
            records = []
            payload["records"] = records
        records.append(record)
        payload["updated_at"] = datetime.now(UTC).isoformat()
        self._write_json(self.manufacturing_trace_path, payload)

    def manufacturing_trace_record_count(self) -> int:
        payload = _read_json_object(self.manufacturing_trace_path)
        records = payload.get("records")
        if not isinstance(records, list):
            return 0
        return len(records)

    def package_manifest_path(self) -> Path:
        return self.root / "agent_package.json"

    def context_summary(self, *, resource_set_store: ResourceSetStore | None = None) -> str:
        effective_store = resource_set_store or self._resource_set_store
        system_state = self.read_system_state()
        action = self.read_action()
        validation = self.read_validation()
        working_set = system_state.working_set()
        active = system_state.active_stage()
        request_text = self._read_text_snippet(self.request_path, limit=360)
        lines = [
            f"Workspace: {self.root}",
            f"Original request: {request_text}" if request_text else "Original request: unavailable",
            f"System state file: {SYSTEM_STATE_FILE} (managed by create_agent_stage; do not edit directly)",
            f"Action file: {ACTION_FILE} (managed by create_agent_control; do not edit directly)",
            f"Resources file: {RESOURCES_FILE}",
            f"Validation file: {VALIDATION_FILE}",
            f"Systems remaining: {working_set['remaining']}/{working_set['total']}",
            "Active system:",
        ]
        if active:
            lines.append(f"- {active.system_id}: {active.status.value} | {active.title}")
            lines.append(f"  owned_files={active.owned_files}")
            lines.append(f"  required_skill={active.required_skill}")
            lines.append(f"  validation_scope={active.validation_scope}")
            if active.read_only_dependencies:
                lines.append(f"  read_only_dependencies={active.read_only_dependencies}")
        completed = [stage for stage in system_state.stages if stage.status.value == "done"]
        if completed:
            lines.append("Completed systems:")
            for stage in completed[-8:]:
                lines.append(f"- {stage.system_id}: {stage.title}")
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


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _assert_inside(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes create-agent workspace: {path}") from exc
