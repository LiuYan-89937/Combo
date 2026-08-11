from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from agent_factory.runtime_protocol.errors import RuntimeErrorEnvelope


ExecutionPreference = Literal["auto", "react", "plan_and_execute"]
ExecutionStrategy = Literal["react", "plan_and_execute"]
RouteDecisionSource = Literal["auto", "user"]
PolicyValueSource = Literal["user_policy", "command"]
RouteIntent = Literal["task", "question", "control", "approval", "continuation"]
ApprovalMode = Literal["ask", "auto", "always_approval"]
RuntimeRole = Literal["main", "temporary"]
ModelOperationKind = Literal[
    "execution_routing",
    "main_turn",
    "temporary_turn",
    "context_compression",
    "tool_output_compression",
    "memory_extraction",
    "scheduler_feedback",
    "embedding",
    "image_generation",
]
RuntimeInstanceStatus = Literal[
    "created",
    "queued",
    "running",
    "waiting_approval",
    "waiting_external",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
]
CapabilityKind = Literal["skill", "tool", "mcp_server", "mcp_tool", "dependency"]
CapabilitySelectionStatus = Literal["selected", "rejected"]
TaskRevisionAction = Literal["created", "continued", "revised", "cancelled", "superseded"]


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


class ProtocolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FrozenProtocolModel(ProtocolModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UserRuntimePolicy(ProtocolModel):
    principal_id: str
    policy_id: str
    revision: int = Field(default=1, ge=1)
    execution_preference: ExecutionPreference = "auto"
    approval_mode: ApprovalMode = "ask"
    model_profile_id: str | None = None
    reasoning_intensity: int | None = Field(default=None, ge=0)
    request_timeout_seconds: int = Field(default=300, ge=1)
    max_model_attempts: int = Field(default=1, ge=1)
    max_parallel_temporary_agents: int = Field(default=5, ge=1)
    max_temporary_delegation_depth: int = Field(default=0, ge=0)
    delegation_grant_ttl_seconds: int = Field(default=900, ge=1)
    timezone: str
    updated_at: str = Field(default_factory=utc_now_text)

    @field_validator("principal_id", "policy_id", "timezone")
    @classmethod
    def _policy_id_is_present(cls, value: str) -> str:
        return _required_text(value, "policy_id")

    @field_validator("model_profile_id")
    @classmethod
    def _optional_profile_id(cls, value: str | None) -> str | None:
        return _optional_text(value)


class ModelSelectionSnapshot(FrozenProtocolModel):
    operation: ModelOperationKind
    profile_id: str
    profile_revision: int = Field(ge=1)
    credential_resource_id: str
    credential_revision: int = Field(ge=1)
    provider: str
    model_name: str
    temperature: float | None = Field(default=None, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=1)

    @field_validator(
        "profile_id",
        "credential_resource_id",
        "provider",
        "model_name",
    )
    @classmethod
    def _required_model_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)


class RuntimePolicySnapshot(FrozenProtocolModel):
    snapshot_id: str = Field(default_factory=lambda: uuid4().hex)
    principal_id: str
    source_policy_id: str
    source_policy_revision: int = Field(ge=1)
    execution_preference: ExecutionPreference
    execution_preference_source: PolicyValueSource
    approval_mode: ApprovalMode
    approval_mode_source: PolicyValueSource
    model: ModelSelectionSnapshot
    reasoning_intensity: int | None = Field(default=None, ge=0)
    request_timeout_seconds: int = Field(ge=1)
    max_model_attempts: int = Field(ge=1)
    max_parallel_temporary_agents: int = Field(ge=1)
    max_temporary_delegation_depth: int = Field(ge=0)
    delegation_grant_ttl_seconds: int = Field(ge=1)
    timezone: str
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator("snapshot_id", "principal_id", "source_policy_id", "timezone")
    @classmethod
    def _required_policy_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)


class RouteDecision(FrozenProtocolModel):
    strategy: ExecutionStrategy
    decision_source: RouteDecisionSource
    intent: RouteIntent
    reason: str
    capability_requirements: tuple[str, ...] = ()
    needs_clarification: bool = False

    @field_validator("reason")
    @classmethod
    def _reason_is_present(cls, value: str) -> str:
        return _required_text(value, "reason")

    @field_validator("capability_requirements")
    @classmethod
    def _normalize_requirements(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_text_tuple(value)


class CapabilityRevisionRef(FrozenProtocolModel):
    capability_id: str
    kind: CapabilityKind
    resolved_version: str
    revision: int = Field(ge=1)
    content_digest: str

    @field_validator("capability_id", "resolved_version", "content_digest")
    @classmethod
    def _required_capability_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)


class DependencyEnvironmentRef(FrozenProtocolModel):
    environment_id: str
    revision: int = Field(ge=1)
    content_digest: str
    capability_refs: tuple[CapabilityRevisionRef, ...]

    @field_validator("environment_id", "content_digest")
    @classmethod
    def _required_environment_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @model_validator(mode="after")
    def _capability_refs_are_unique(self) -> "DependencyEnvironmentRef":
        if not self.capability_refs:
            raise ValueError("dependency environment requires capability refs")
        identities = {(item.capability_id, item.revision) for item in self.capability_refs}
        if len(identities) != len(self.capability_refs):
            raise ValueError("dependency environment capability refs must be unique")
        if any(item.kind != "dependency" for item in self.capability_refs):
            raise ValueError("dependency environment may only reference dependency capabilities")
        return self


class CapabilityProjectionSnapshot(FrozenProtocolModel):
    capability_id: str
    kind: CapabilityKind
    revision: int = Field(ge=1)
    content_digest: str
    adapter_id: str
    adapter_revision: str
    runtime_definition_schema: str
    runtime_definition: dict[str, JsonValue]
    model_prompt_fragments: tuple[str, ...] = ()
    model_tool_ids: tuple[str, ...] = ()
    projection_digest: str = ""

    @field_validator(
        "capability_id",
        "content_digest",
        "adapter_id",
        "adapter_revision",
        "runtime_definition_schema",
    )
    @classmethod
    def _required_projection_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator("model_prompt_fragments", "model_tool_ids")
    @classmethod
    def _projection_lists_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_text_tuple(value)

    @model_validator(mode="after")
    def _projection_digest_matches(self) -> "CapabilityProjectionSnapshot":
        if self.kind not in {"tool", "mcp_tool"} and self.model_tool_ids:
            raise ValueError("only tool capability projections may expose model tool IDs")
        payload = {
            "capability_id": self.capability_id,
            "kind": self.kind,
            "revision": self.revision,
            "content_digest": self.content_digest,
            "adapter_id": self.adapter_id,
            "adapter_revision": self.adapter_revision,
            "runtime_definition_schema": self.runtime_definition_schema,
            "runtime_definition": self.runtime_definition,
            "model_prompt_fragments": list(self.model_prompt_fragments),
            "model_tool_ids": list(self.model_tool_ids),
        }
        expected = sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if self.projection_digest and self.projection_digest != expected:
            raise ValueError("capability projection digest does not match projection")
        object.__setattr__(self, "projection_digest", expected)
        return self


class CapabilitySelection(FrozenProtocolModel):
    capability_id: str
    kind: CapabilityKind
    status: CapabilitySelectionStatus
    reason: str
    evidence_ids: tuple[str, ...]
    score: float | None = None
    resolved: CapabilityRevisionRef | None = None

    @field_validator("capability_id", "reason")
    @classmethod
    def _required_selection_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_ids_are_present(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = _unique_text_tuple(value)
        if not normalized:
            raise ValueError("capability selection requires evidence IDs")
        return normalized

    @model_validator(mode="after")
    def _selected_capability_has_revision(self) -> "CapabilitySelection":
        if self.status == "selected" and self.resolved is None:
            raise ValueError("selected capability requires resolved revision")
        if self.status == "rejected" and self.resolved is not None:
            raise ValueError("rejected capability cannot carry resolved revision")
        if self.resolved is not None and (
            self.resolved.capability_id != self.capability_id
            or self.resolved.kind != self.kind
        ):
            raise ValueError("capability selection resolved revision identity differs from selection")
        return self


class CapabilityToolAliasBinding(FrozenProtocolModel):
    model_alias: str
    capability_id: str
    kind: Literal["tool", "mcp_tool"]
    revision: int = Field(ge=1)
    content_digest: str

    @field_validator("model_alias", "capability_id", "content_digest")
    @classmethod
    def _binding_text_is_present(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)


class CapabilitySnapshot(FrozenProtocolModel):
    snapshot_id: str = ""
    schema_version: Literal["capability_snapshot.v3"] = "capability_snapshot.v3"
    selections: tuple[CapabilitySelection, ...]
    projections: tuple[CapabilityProjectionSnapshot, ...]
    tool_ids: tuple[str, ...]
    tool_aliases: tuple[CapabilityToolAliasBinding, ...] = ()
    dependency_environment: DependencyEnvironmentRef | None = None
    content_digest: str = ""

    @field_validator("schema_version")
    @classmethod
    def _required_snapshot_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator("tool_ids")
    @classmethod
    def _unique_tool_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_text_tuple(value)

    @field_validator("tool_aliases")
    @classmethod
    def _unique_aliases(
        cls,
        value: tuple[CapabilityToolAliasBinding, ...],
    ) -> tuple[CapabilityToolAliasBinding, ...]:
        aliases = [item.model_alias for item in value]
        if len(aliases) != len(set(aliases)):
            raise ValueError("capability snapshot tool aliases must be unique")
        return value

    @model_validator(mode="after")
    def _selected_surface_is_closed(self) -> "CapabilitySnapshot":
        selection_ids = [item.capability_id for item in self.selections]
        if len(selection_ids) != len(set(selection_ids)):
            raise ValueError("capability snapshot selections must use unique capability IDs")
        selected = {
            item.capability_id: item
            for item in self.selections
            if item.status == "selected"
        }
        projection_by_id = {item.capability_id: item for item in self.projections}
        if len(projection_by_id) != len(self.projections):
            raise ValueError("capability snapshot projections must use unique capability IDs")
        if set(projection_by_id) != set(selected):
            raise ValueError("capability snapshot projections must exactly match selected capabilities")
        for capability_id, projection in projection_by_id.items():
            resolved = selected[capability_id].resolved
            if resolved is None or (
                projection.kind != resolved.kind
                or projection.revision != resolved.revision
                or projection.content_digest != resolved.content_digest
            ):
                raise ValueError("capability projection identity differs from selected revision")
        projected_aliases = tuple(
            CapabilityToolAliasBinding(
                model_alias=alias,
                capability_id=projection.capability_id,
                kind=projection.kind,
                revision=projection.revision,
                content_digest=projection.content_digest,
            )
            for projection in self.projections
            for alias in projection.model_tool_ids
        )
        projected_tool_ids = tuple(item.model_alias for item in projected_aliases)
        if self.tool_ids != projected_tool_ids:
            raise ValueError("capability snapshot tool IDs must exactly match ordered model aliases")
        if self.tool_aliases != projected_aliases:
            raise ValueError("capability snapshot tool alias bindings differ from adapter projections")
        for binding in self.tool_aliases:
            selection = selected.get(binding.capability_id)
            if selection is None or selection.kind != binding.kind or selection.resolved is None:
                raise ValueError("capability snapshot tool alias references an unselected tool capability")
            if (
                selection.resolved.revision != binding.revision
                or selection.resolved.content_digest != binding.content_digest
            ):
                raise ValueError("capability snapshot tool alias revision differs from selected capability")
        if self.dependency_environment is not None:
            expected = {
                (
                    item.resolved.capability_id,
                    item.resolved.revision,
                    item.resolved.content_digest,
                )
                for item in selected.values()
                if item.kind == "dependency" and item.resolved is not None
            }
            actual = {
                (item.capability_id, item.revision, item.content_digest)
                for item in self.dependency_environment.capability_refs
            }
            if actual != expected:
                raise ValueError(
                    "capability snapshot dependency environment differs from selected dependencies"
                )
        elif any(item.kind == "dependency" for item in selected.values()):
            raise ValueError("selected dependencies require an immutable dependency environment")
        return self

    @model_validator(mode="after")
    def _content_digest_matches_payload(self) -> "CapabilitySnapshot":
        expected = self.computed_digest()
        if self.content_digest and self.content_digest != expected:
            raise ValueError("capability snapshot content_digest does not match payload")
        expected_snapshot_id = f"capability_snapshot:{expected}"
        if self.snapshot_id and self.snapshot_id != expected_snapshot_id:
            raise ValueError("capability snapshot ID must be derived from its content digest")
        object.__setattr__(self, "content_digest", expected)
        object.__setattr__(self, "snapshot_id", expected_snapshot_id)
        return self

    def computed_digest(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "selections": [item.model_dump(mode="json") for item in self.selections],
            "projections": [item.model_dump(mode="json") for item in self.projections],
            "tool_ids": list(self.tool_ids),
            "tool_aliases": [item.model_dump(mode="json") for item in self.tool_aliases],
            "dependency_environment": (
                self.dependency_environment.model_dump(mode="json")
                if self.dependency_environment is not None
                else None
            ),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


class RuntimeRequest(FrozenProtocolModel):
    request_id: str
    principal_id: str
    session_id: str
    turn_id: str
    workspace_id: str
    runtime_role: RuntimeRole
    strategy: ExecutionStrategy
    route_decision: RouteDecision
    policy_snapshot: RuntimePolicySnapshot
    capability_snapshot_id: str
    approval_mode: ApprovalMode
    task_revision: int = Field(ge=1)
    parent_runtime_instance_id: str | None = None
    task_id: str | None = None
    delegation_grant_id: str | None = None
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "request_id",
        "principal_id",
        "session_id",
        "turn_id",
        "workspace_id",
        "capability_snapshot_id",
    )
    @classmethod
    def _required_request_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator("parent_runtime_instance_id", "task_id", "delegation_grant_id")
    @classmethod
    def _optional_parent_runtime(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def _role_matches_parent(self) -> "RuntimeRequest":
        if self.runtime_role == "main" and self.parent_runtime_instance_id is not None:
            raise ValueError("main runtime cannot have parent_runtime_instance_id")
        if self.runtime_role == "temporary" and self.parent_runtime_instance_id is None:
            raise ValueError("temporary runtime requires parent_runtime_instance_id")
        delegation_fields = (self.task_id, self.delegation_grant_id)
        if self.runtime_role == "main" and any(item is not None for item in delegation_fields):
            raise ValueError("main runtime cannot carry delegated task identity")
        if self.runtime_role == "temporary" and any(item is None for item in delegation_fields):
            raise ValueError("temporary runtime requires task and delegation grant identities")
        if self.approval_mode != self.policy_snapshot.approval_mode:
            raise ValueError("request approval_mode must match policy snapshot")
        if self.strategy != self.route_decision.strategy:
            raise ValueError("request strategy must match route decision")
        if self.principal_id != self.policy_snapshot.principal_id:
            raise ValueError("request principal_id must match policy snapshot")
        expected_operation = "main_turn" if self.runtime_role == "main" else "temporary_turn"
        if self.policy_snapshot.model.operation != expected_operation:
            raise ValueError("request runtime_role does not match model operation")
        return self


class RuntimeExecutionIdentity(FrozenProtocolModel):
    principal_id: str
    request_id: str
    runtime_instance_id: str
    attempt_id: str
    session_id: str
    turn_id: str
    workspace_id: str
    runtime_role: RuntimeRole
    parent_runtime_instance_id: str | None = None
    task_id: str | None = None
    delegation_grant_id: str | None = None
    task_revision: int = Field(ge=1)
    generation: int = Field(ge=1)

    @field_validator(
        "principal_id",
        "request_id",
        "runtime_instance_id",
        "attempt_id",
        "session_id",
        "turn_id",
        "workspace_id",
    )
    @classmethod
    def _required_identity_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator("parent_runtime_instance_id", "task_id", "delegation_grant_id")
    @classmethod
    def _optional_identity_parent(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def _identity_role_matches_parent(self) -> "RuntimeExecutionIdentity":
        if self.runtime_role == "main" and self.parent_runtime_instance_id is not None:
            raise ValueError("main runtime identity cannot carry a parent runtime")
        if self.runtime_role == "temporary" and self.parent_runtime_instance_id is None:
            raise ValueError("temporary runtime identity requires a parent runtime")
        delegation_fields = (self.task_id, self.delegation_grant_id)
        if self.runtime_role == "main" and any(item is not None for item in delegation_fields):
            raise ValueError("main runtime identity cannot carry delegated task identity")
        if self.runtime_role == "temporary" and any(item is None for item in delegation_fields):
            raise ValueError("temporary runtime identity requires task and grant identities")
        return self


class RuntimeInstance(ProtocolModel):
    runtime_instance_id: str = Field(default_factory=lambda: uuid4().hex)
    request: RuntimeRequest
    capability_snapshot_id: str
    generation: int = Field(default=1, ge=1)
    status: RuntimeInstanceStatus = "created"
    attempt_id: str | None = None
    stream_id: str
    last_event_sequence: int = Field(default=0, ge=0)
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)
    terminal_at: str | None = None
    error: RuntimeErrorEnvelope | None = None
    cancel_requested_at: str | None = None
    cancel_reason: str | None = None
    cancel_command_id: str | None = None

    @field_validator("runtime_instance_id", "capability_snapshot_id", "stream_id")
    @classmethod
    def _required_instance_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator(
        "attempt_id",
        "terminal_at",
        "cancel_requested_at",
        "cancel_reason",
        "cancel_command_id",
    )
    @classmethod
    def _optional_instance_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def _instance_matches_request(self) -> "RuntimeInstance":
        if self.capability_snapshot_id != self.request.capability_snapshot_id:
            raise ValueError("runtime instance capability snapshot does not match request")
        terminal = self.status in {"completed", "failed", "cancelled"}
        if terminal != bool(self.terminal_at):
            raise ValueError("terminal runtime status and terminal_at must be set together")
        if self.status == "failed" and self.error is None:
            raise ValueError("failed runtime instance requires error")
        if self.error is not None:
            if self.error.runtime_instance_id != self.runtime_instance_id:
                raise ValueError("runtime error instance identity does not match")
            if self.error.request_id != self.request.request_id:
                raise ValueError("runtime error request identity does not match")
            if self.error.terminal_status != self.status:
                raise ValueError("runtime error terminal status does not match instance")
        cancellation_fields = (
            self.cancel_requested_at,
            self.cancel_reason,
            self.cancel_command_id,
        )
        if any(item is not None for item in cancellation_fields) and any(
            item is None for item in cancellation_fields
        ):
            raise ValueError("runtime cancellation request fields must be set together")
        return self


class TaskRevision(FrozenProtocolModel):
    revision: int = Field(ge=1)
    action: TaskRevisionAction
    user_message_id: str
    instruction: str
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator("user_message_id", "instruction")
    @classmethod
    def _required_revision_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)


class AttachmentRevisionRef(FrozenProtocolModel):
    attachment_id: str
    revision: int = Field(ge=1)
    content_digest: str

    @field_validator("attachment_id", "content_digest")
    @classmethod
    def _required_attachment_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)


class TaskEnvelope(FrozenProtocolModel):
    task_id: str
    principal_id: str
    parent_runtime_instance_id: str
    delegation_grant_id: str
    capability_snapshot_id: str
    task_revision: int = Field(ge=1)
    parent_task_revision: int = Field(ge=1)
    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    context_facts: tuple[str, ...] = ()
    input_artifacts: tuple[AttachmentRevisionRef, ...] = ()
    workspace_id: str
    allowed_write_roots: tuple[str, ...] = ()
    capability_requirements: tuple[str, ...] = ()
    approval_mode: ApprovalMode
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "task_id",
        "principal_id",
        "parent_runtime_instance_id",
        "delegation_grant_id",
        "capability_snapshot_id",
        "objective",
        "workspace_id",
    )
    @classmethod
    def _required_envelope_text(cls, value: str, info: Any) -> str:
        return _required_text(value, info.field_name)

    @field_validator(
        "acceptance_criteria",
        "context_facts",
        "allowed_write_roots",
        "capability_requirements",
    )
    @classmethod
    def _normalize_envelope_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _unique_text_tuple(value)


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _unique_text_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _required_text(value, "list item")
        if text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return tuple(normalized)
