from __future__ import annotations

from typing import Annotated, Literal, Protocol, Union

from pydantic import Field, field_validator, model_validator

from combo.runtime_protocol.contracts import FrozenProtocolModel


class SessionDeepLink(FrozenProtocolModel):
    kind: Literal["session"] = "session"
    session_id: str
    turn_id: str | None = None

    @field_validator("session_id")
    @classmethod
    def _session_id_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("session_id must not be empty")
        return text

    @field_validator("turn_id")
    @classmethod
    def _optional_turn_id(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None


class WorkspaceDeepLink(FrozenProtocolModel):
    kind: Literal["workspace"] = "workspace"
    workspace_id: str

    @field_validator("workspace_id")
    @classmethod
    def _workspace_id_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("workspace_id must not be empty")
        return text


class ArtifactDeepLink(FrozenProtocolModel):
    kind: Literal["artifact"] = "artifact"
    artifact_id: str
    revision: int = Field(ge=1)

    @field_validator("artifact_id")
    @classmethod
    def _artifact_id_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("artifact_id must not be empty")
        return text


DeepLinkTarget = Annotated[
    Union[SessionDeepLink, WorkspaceDeepLink, ArtifactDeepLink],
    Field(discriminator="kind"),
]


class DeepLinkResolution(FrozenProtocolModel):
    status: Literal["resolved", "retired", "invalid"]
    target: DeepLinkTarget | None = None
    error_code: str | None = None

    @field_validator("error_code")
    @classmethod
    def _optional_error_code(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _resolution_is_consistent(self) -> "DeepLinkResolution":
        if self.status == "resolved":
            if self.target is None or self.error_code is not None:
                raise ValueError("resolved deep link requires target and no error_code")
        elif self.target is not None or self.error_code is None:
            raise ValueError("retired and invalid deep links require error_code and no target")
        return self


class DeepLinkResolver(Protocol):
    def resolve(self, value: str) -> DeepLinkResolution: ...
