from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RUNTIME_PROTOCOL_VERSION = "dynamic_runtime.v14"
RUNTIME_SCHEMA_VERSION = "dynamic_runtime_schema.v13"


class RuntimeProtocolDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: str = RUNTIME_PROTOCOL_VERSION
    schema_version: str = RUNTIME_SCHEMA_VERSION
    build_revision: str

    @field_validator(
        "protocol_version",
        "schema_version",
        "build_revision",
    )
    @classmethod
    def _required_text(cls, value: str, info: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{info.field_name} must not be empty")
        return text

    def matches(self, other: "RuntimeProtocolDescriptor") -> bool:
        return (
            self.protocol_version == other.protocol_version
            and self.schema_version == other.schema_version
            and self.build_revision == other.build_revision
        )


class RuntimeProtocolHandshake(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    client_instance_id: str
    client: RuntimeProtocolDescriptor

    @field_validator("client_instance_id")
    @classmethod
    def _client_instance_id_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("client_instance_id must not be empty")
        return text


class RuntimeProtocolHandshakeResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["accepted", "incompatible"]
    server: RuntimeProtocolDescriptor
    client_instance_id: str
    error_code: str | None = None

    @field_validator("client_instance_id")
    @classmethod
    def _result_client_instance_id_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("client_instance_id must not be empty")
        return text

    @field_validator("error_code")
    @classmethod
    def _optional_error_code(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _status_matches_error(self) -> "RuntimeProtocolHandshakeResult":
        if self.status == "accepted" and self.error_code is not None:
            raise ValueError("accepted handshake cannot carry error_code")
        if self.status == "incompatible" and self.error_code is None:
            raise ValueError("incompatible handshake requires error_code")
        return self
