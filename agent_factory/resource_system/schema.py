from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResourceIdentity(BaseModel):
    """Immutable owner and revision identity for one runtime resource."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    owner_kind: Literal["capability", "mcp_server", "tool"]
    owner_id: str
    owner_revision: int = Field(ge=1)
    resource_id: str
    resource_revision: int = Field(ge=1)

    @field_validator("owner_id", "resource_id")
    @classmethod
    def _text_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("resource identity fields must not be empty")
        return text

    @property
    def storage_key(self) -> str:
        return ":".join(
            (
                self.owner_kind,
                self.owner_id,
                str(self.owner_revision),
                self.resource_id,
                str(self.resource_revision),
            )
        )


class ResourceDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: ResourceIdentity
    description: str = ""
    required: bool = True
    value_schema: dict[str, Any] = Field(default_factory=dict)
    secret_fields: tuple[str, ...] = ()
    purpose: str = "runtime"

    @field_validator("purpose")
    @classmethod
    def _purpose_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("resource purpose must not be empty")
        return text
