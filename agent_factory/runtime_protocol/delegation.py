from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from agent_factory.runtime_protocol.contracts import ApprovalMode, FrozenProtocolModel, utc_now_text


DelegatedTaskEventType = Literal[
    "progress",
    "question",
    "approval_required",
    "capability_request",
    "artifact",
    "result",
    "failed",
    "cancelled",
]


class DelegatedTaskEvent(FrozenProtocolModel):
    event_id: str
    task_id: str
    task_revision: int = Field(ge=1)
    parent_task_revision: int = Field(ge=1)
    sequence: int = Field(ge=1)
    event_type: DelegatedTaskEventType
    principal_id: str
    parent_runtime_instance_id: str
    child_runtime_instance_id: str
    child_attempt_id: str
    payload: dict[str, Any]
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "event_id",
        "task_id",
        "principal_id",
        "parent_runtime_instance_id",
        "child_runtime_instance_id",
        "child_attempt_id",
        "created_at",
    )
    @classmethod
    def _required_event_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{getattr(info, 'field_name', 'value')} must not be empty")
        return text


class DelegationGrant(FrozenProtocolModel):
    grant_id: str
    principal_id: str
    parent_runtime_instance_id: str
    child_runtime_instance_id: str
    task_id: str
    task_revision: int = Field(ge=1)
    parent_capability_snapshot_id: str
    child_capability_snapshot_id: str
    workspace_id: str
    approval_mode: ApprovalMode
    allowed_write_roots: tuple[str, ...] = ()
    allowed_artifact_ids: tuple[str, ...] = ()
    allowed_tool_aliases: tuple[str, ...] = ()
    maximum_delegation_depth: int = Field(ge=0)
    remaining_delegation_depth: int = Field(ge=0)
    expires_at: str
    created_at: str = Field(default_factory=utc_now_text)
    content_digest: str = ""

    @field_validator(
        "grant_id",
        "principal_id",
        "parent_runtime_instance_id",
        "child_runtime_instance_id",
        "task_id",
        "parent_capability_snapshot_id",
        "child_capability_snapshot_id",
        "workspace_id",
        "expires_at",
        "created_at",
    )
    @classmethod
    def _required_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{getattr(info, 'field_name', 'value')} must not be empty")
        return text

    @field_validator("allowed_write_roots", "allowed_artifact_ids", "allowed_tool_aliases")
    @classmethod
    def _unique_scope_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(str(item or "").strip() for item in value))
        if any(not item for item in normalized):
            raise ValueError("delegation scope values must not be empty")
        return normalized

    @model_validator(mode="after")
    def _validate_grant(self) -> "DelegationGrant":
        if self.parent_runtime_instance_id == self.child_runtime_instance_id:
            raise ValueError("delegation parent and child runtime identities must differ")
        if self.remaining_delegation_depth > self.maximum_delegation_depth:
            raise ValueError("remaining delegation depth exceeds the grant maximum")
        try:
            created = datetime.fromisoformat(self.created_at)
            expires = datetime.fromisoformat(self.expires_at)
        except ValueError as exc:
            raise ValueError("delegation timestamps must be ISO 8601 values") from exc
        if created.tzinfo is None or expires.tzinfo is None:
            raise ValueError("delegation timestamps must include an explicit timezone")
        if expires <= created:
            raise ValueError("delegation grant must expire after it is created")
        expected = self.computed_digest()
        if self.content_digest and self.content_digest != expected:
            raise ValueError("delegation grant content_digest does not match its scope")
        object.__setattr__(self, "content_digest", expected)
        return self

    def computed_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"content_digest"})
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(encoded).hexdigest()
