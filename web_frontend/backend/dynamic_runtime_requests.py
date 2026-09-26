from __future__ import annotations

from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from combo.dynamic_runtime.mermaid_repair import MAX_MERMAID_ERROR_CHARS, MAX_MERMAID_SOURCE_CHARS
from combo.runtime_protocol import ApprovalMode, DEFAULT_REASONING_INTENSITY, ExecutionPreference


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str

    @field_validator("title")
    @classmethod
    def _title_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("conversation title must not be empty")
        return text


class MainAgentCapabilityProfileWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    capability_ids: list[str]
    mcp_server_ids: list[str]

    @field_validator("capability_ids", "mcp_server_ids")
    @classmethod
    def _capability_ids_are_unique(cls, values: list[str]) -> list[str]:
        normalized = [str(value or "").strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("main Agent capability profile contains an empty capability ID")
        if len(normalized) != len(set(normalized)):
            raise ValueError("main Agent capability profile contains duplicate capability IDs")
        return normalized


class RuntimePolicyWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int | None = Field(default=None, ge=1)
    execution_preference: ExecutionPreference
    approval_mode: ApprovalMode
    model_profile_id: str
    reasoning_intensity: int = Field(default=DEFAULT_REASONING_INTENSITY, ge=1, le=3)
    request_timeout_seconds: int = Field(ge=1)
    builtin_tool_timeout_seconds: int = Field(default=300, ge=1, le=3600)
    browser_operation_timeout_ms: int = Field(default=30_000, ge=1_000, le=600_000)
    browser_navigation_timeout_ms: int = Field(default=45_000, ge=1_000, le=600_000)
    max_model_attempts: int = Field(ge=1)
    max_parallel_temporary_agents: int = Field(ge=0)
    context_compression_detail: Literal["concise", "standard", "detailed"] = "standard"
    context_compression_keep_recent_messages: int = Field(default=12, ge=0, le=128)
    memory_auto_recall_enabled: bool = True
    memory_agent_write_enabled: bool = True
    memory_max_injected_items: int = Field(default=8, ge=1, le=64)
    memory_max_injected_tokens: int = Field(default=1200, ge=100, le=32000)
    computer_use_enabled: bool | None = None
    max_temporary_delegation_depth: int = Field(ge=0)
    delegation_grant_ttl_seconds: int = Field(ge=1)
    timezone: str

    @field_validator("model_profile_id")
    @classmethod
    def _model_profile_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("model_profile_id must not be empty")
        return text

    @field_validator("timezone")
    @classmethod
    def _timezone_is_supported(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("timezone must not be empty")
        try:
            ZoneInfo(text)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {text}") from exc
        return text


class MCPServerProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str

    @field_validator("capability_id")
    @classmethod
    def _capability_id_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("capability_id must not be empty")
        return text


class MCPResourceReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    uri: str | None = None
    uri_template: str | None = None
    arguments: dict[str, str] = Field(default_factory=dict)

    @field_validator("capability_id")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("MCP resource capability_id must not be empty")
        return text

    @model_validator(mode="after")
    def _resource_reference_is_unambiguous(self) -> "MCPResourceReadRequest":
        self.uri = str(self.uri or "").strip() or None
        self.uri_template = str(self.uri_template or "").strip() or None
        if (self.uri is None) == (self.uri_template is None):
            raise ValueError("provide exactly one of MCP resource uri or uri_template")
        self.arguments = {str(name): str(argument) for name, argument in self.arguments.items()}
        return self


class MCPPromptGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    name: str
    arguments: dict[str, str] = Field(default_factory=dict)

    @field_validator("capability_id", "name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("MCP prompt capability_id and name must not be empty")
        return text

    @field_validator("arguments")
    @classmethod
    def _arguments_are_strings(cls, value: dict[str, str]) -> dict[str, str]:
        return {str(name): str(argument) for name, argument in value.items()}


class MCPBindingReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["process_environment", "literal"]
    name: str | None = None
    value: str | None = None

    @model_validator(mode="after")
    def _reference_matches_source(self) -> "MCPBindingReference":
        if self.source == "process_environment" and (not self.name or self.value is not None):
            raise ValueError("process environment binding requires name and forbids value")
        if self.source == "literal" and (self.value is None or self.name is not None):
            raise ValueError("literal binding requires value and forbids name")
        return self


class MCPServerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_registry_digest: str
    server_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    display_name: str
    description: str
    transport: Literal["stdio", "streamable_http", "sse"]
    command: str | None = None
    arguments: tuple[str, ...] = ()
    working_directory: str | None = None
    endpoint: str | None = None
    environment_bindings: dict[str, str | MCPBindingReference] = Field(default_factory=dict)
    header_bindings: dict[str, str | MCPBindingReference] = Field(default_factory=dict)
    connect_timeout_seconds: float = Field(default=30.0, gt=0)
    request_timeout_seconds: float = Field(default=120.0, gt=0)
    max_parallel_requests: int = Field(default=1, ge=1)
    risk_level_default: Literal["low", "medium", "high"] = "medium"
    concurrent_default: bool = True

    @field_validator("expected_registry_digest")
    @classmethod
    def _registry_digest_is_sha256(cls, value: str) -> str:
        text = str(value or "").strip().lower()
        if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
            raise ValueError("expected_registry_digest must be lowercase SHA-256")
        return text

    @field_validator("display_name", "description")
    @classmethod
    def _server_text_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("MCP server name and description must not be empty")
        return text

    @field_validator("command", "working_directory", "endpoint")
    @classmethod
    def _optional_server_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("environment_bindings", "header_bindings")
    @classmethod
    def _binding_names_are_present(cls, value: dict[str, str | MCPBindingReference]) -> dict[str, str | MCPBindingReference]:
        normalized = {
            str(target).strip(): source if isinstance(source, MCPBindingReference) else str(source).strip()
            for target, source in value.items()
        }
        if any(not target or not source for target, source in normalized.items()):
            raise ValueError("MCP binding names must not be empty")
        return normalized

    @model_validator(mode="after")
    def _transport_fields_match(self) -> "MCPServerCreateRequest":
        if self.transport == "stdio":
            if self.command is None or self.endpoint is not None:
                raise ValueError("stdio MCP requires command and forbids endpoint")
        elif self.endpoint is None or self.command is not None or self.arguments:
            raise ValueError("HTTP MCP requires endpoint and forbids command arguments")
        return self

    def registry_document(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "display_name": self.display_name,
            "description": self.description,
            "enabled": True,
            "connection": {
                "transport": self.transport,
                "command": self.command,
                "args": list(self.arguments),
                "cwd": self.working_directory,
                "url": self.endpoint,
                "env": _environment_references(self.environment_bindings),
                "headers": _environment_references(self.header_bindings),
                "connect_timeout_seconds": self.connect_timeout_seconds,
                "request_timeout_seconds": self.request_timeout_seconds,
                "max_parallel_requests": self.max_parallel_requests,
            },
            "defaults": {
                "risk_level": self.risk_level_default,
                "allow_parallel_calls": self.concurrent_default,
                "tool_id_prefix": None,
            },
            "tools": {},
        }


class SkillReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability_id: str
    source_path: str
    expected_content_digest: str

    @field_validator("capability_id", "source_path", "expected_content_digest")
    @classmethod
    def _skill_replace_text_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Skill replacement fields must not be empty")
        return text


class ToolRuntimePolicyWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval: Literal["inherit", "allow", "ask", "deny"]
    risk_level: Literal["low", "medium", "high"]
    allow_parallel_calls: bool
    max_parallel_calls: int = Field(ge=1, le=128)
    timeout_seconds: float | None = Field(gt=0, le=3600)
    output_projection: Literal["compress", "passthrough"]
    output_max_model_chars: int = Field(ge=1000, le=1_000_000)
    retain_raw_output: bool

    @model_validator(mode="after")
    def _parallel_limit_matches_switch(self) -> "ToolRuntimePolicyWriteRequest":
        if not self.allow_parallel_calls and self.max_parallel_calls != 1:
            raise ValueError("disabled parallel calls require max_parallel_calls=1")
        return self


class ToolConfigurationWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_digest: str
    display_name: str
    description: str
    runtime_policy: ToolRuntimePolicyWriteRequest

    @field_validator("expected_content_digest", "display_name", "description")
    @classmethod
    def _required_tool_configuration_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("tool configuration fields must not be empty")
        return text


class ToolParameterWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    type: Literal["string", "integer", "number", "boolean", "object", "array"]
    description: str
    required: bool = True

    @field_validator("description")
    @classmethod
    def _description_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("parameter description must not be empty")
        return text


class ToolContextParameterWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    type: Literal["string", "integer", "number", "boolean", "object", "array"]
    value: str = ""


class ToolPackageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,127}$")
    model_alias: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    display_name: str
    description: str
    keywords: list[str] = Field(default_factory=list)
    parameters: list[ToolParameterWriteRequest] = Field(default_factory=list)
    context_parameters: list[ToolContextParameterWriteRequest] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    runtime_policy: ToolRuntimePolicyWriteRequest

    @field_validator("display_name", "description")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("ToolPackage fields must not be empty")
        return text

    @model_validator(mode="after")
    def _unique_parameters(self) -> "ToolPackageCreateRequest":
        names = [item.name for item in (*self.parameters, *self.context_parameters)]
        if len(names) != len(set(names)):
            raise ValueError("ToolPackage parameter names must be unique")
        return self


class ToolPackageContentWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_digest: str
    files: dict[str, str]
    manifest: dict[str, Any] | None = None
    context_parameters: list[ToolContextParameterWriteRequest] | None = None

    @field_validator("expected_content_digest")
    @classmethod
    def _digest_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("expected_content_digest must not be empty")
        return text


class SkillContentWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_digest: str
    metadata: dict[str, Any]
    instructions: str
    resources: dict[str, str] = Field(default_factory=dict)

    @field_validator("expected_content_digest", "instructions")
    @classmethod
    def _required_skill_content_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Skill content fields must not be empty")
        return text


class SkillHubSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str

    @field_validator("query")
    @classmethod
    def _query_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("SkillHub query must not be empty")
        return text


class SkillHubInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill: str

    @field_validator("skill")
    @classmethod
    def _skill_is_present(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("SkillHub skill must not be empty")
        return text


class MermaidRepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=MAX_MERMAID_SOURCE_CHARS)
    parser_error: str = Field(default="", max_length=MAX_MERMAID_ERROR_CHARS)


def _environment_references(
    bindings: dict[str, str | MCPBindingReference],
) -> dict[str, dict[str, str]]:
    return {
        target: (
            source.model_dump(exclude_none=True)
            if isinstance(source, MCPBindingReference)
            else {"source": "process_environment", "name": source}
        )
        for target, source in bindings.items()
    }

