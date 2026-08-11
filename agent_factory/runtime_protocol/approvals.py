from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from agent_factory.runtime_protocol.contracts import FrozenProtocolModel, utc_now_text


ApprovalGrantStatus = Literal["active", "revoked", "expired"]


class CapabilityApprovalGrant(FrozenProtocolModel):
    grant_id: str = Field(default_factory=lambda: uuid4().hex)
    principal_id: str
    capability_id: str
    capability_revision: int = Field(ge=1)
    capability_content_digest: str
    model_alias: str
    resource_scope_digest: str
    policy_id: str
    policy_revision: int = Field(ge=1)
    status: ApprovalGrantStatus = "active"
    created_at: str = Field(default_factory=utc_now_text)
    expires_at: str | None = None
    revoked_at: str | None = None

    @field_validator(
        "grant_id",
        "principal_id",
        "capability_id",
        "capability_content_digest",
        "model_alias",
        "resource_scope_digest",
        "policy_id",
    )
    @classmethod
    def _required_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{getattr(info, 'field_name', 'value')} must not be empty")
        return text

    @field_validator("expires_at", "revoked_at")
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _status_timestamps_match(self) -> "CapabilityApprovalGrant":
        if self.status == "revoked" and self.revoked_at is None:
            raise ValueError("revoked approval grant requires revoked_at")
        if self.status != "revoked" and self.revoked_at is not None:
            raise ValueError("only revoked approval grant may carry revoked_at")
        return self
