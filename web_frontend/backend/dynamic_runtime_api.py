from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable, Literal, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from combo.exception_details import exception_summary
from combo.sensitive_data import redact_sensitive_text
from combo.dynamic_runtime import (
    DynamicRuntimeApplication,
    DynamicRuntimeSupervisor,
    RuntimeEventBroadcaster,
)
from combo.dynamic_runtime.repositories import utc_now_text
from combo.runtime_protocol import (
    CommandEnvelope,
    CommandReceipt,
    RuntimeProtocolDescriptor,
    RuntimeProtocolHandshake,
    RuntimeProtocolHandshakeResult,
    UserRuntimePolicy,
)


class RequestPrincipalResolver(Protocol):
    def resolve(self, request: Request) -> str:
        ...


class CapabilityPoolManager(Protocol):
    def capability_pool_snapshot(self) -> dict[str, object]:
        ...

    def main_agent_capability_profile(self) -> dict[str, object]:
        ...

    def replace_main_agent_capability_profile(
        self,
        *,
        expected_revision: int,
        capability_ids: tuple[str, ...],
        mcp_server_ids: tuple[str, ...],
    ) -> dict[str, object]:
        ...

    def probe_mcp_server(self, capability_id: str) -> dict[str, object]:
        ...

    def read_mcp_resource(
        self,
        capability_id: str,
        uri: str | None,
        uri_template: str | None,
        arguments: dict[str, str],
    ) -> dict[str, object]:
        ...

    def get_mcp_prompt(
        self,
        capability_id: str,
        name: str,
        arguments: dict[str, str],
    ) -> dict[str, object]:
        ...

    def skillhub_status(self) -> dict[str, Any]:
        ...

    def search_skillhub(self, query: str) -> dict[str, Any]:
        ...

    def install_skillhub_skill(self, skill: str) -> dict[str, object]:
        ...

    def import_skill_folder(self, source_path: str) -> dict[str, object]:
        ...

    def create_tool_package(
        self,
        payload: dict[str, Any],
        main_source: str,
        *,
        resource_files: dict[str, bytes] | None = None,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, object]:
        ...

    def validate_tool_package(
        self,
        payload: dict[str, Any],
        main_source: str,
        *,
        resource_files: dict[str, bytes] | None = None,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, object]:
        ...

    def transcribe_tool_source(self, source: str, *, filename: str) -> dict[str, object]:
        ...

    def add_mcp_server(
        self,
        server: dict[str, Any],
        *,
        expected_registry_digest: str,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, object]:
        ...

    def replace_mcp_server(
        self,
        server_id: str,
        server: dict[str, Any],
        *,
        expected_registry_digest: str,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, object]:
        ...

    def delete_mcp_server(
        self,
        server_id: str,
        *,
        expected_registry_digest: str,
    ) -> dict[str, object]:
        ...

    def delete_tool_package(
        self,
        capability_id: str,
        *,
        expected_content_digest: str,
    ) -> dict[str, object]:
        ...

    def delete_skill(
        self,
        capability_id: str,
        *,
        expected_content_digest: str,
    ) -> dict[str, object]:
        ...

    def replace_tool_configuration(
        self,
        *,
        capability_id: str,
        expected_content_digest: str,
        display_name: str,
        description: str,
        runtime_policy: dict[str, Any],
    ) -> dict[str, object]:
        ...

    def tool_package_editor_document(self, capability_id: str) -> dict[str, object]:
        ...

    def replace_tool_package_content(
        self,
        *,
        capability_id: str,
        expected_content_digest: str,
        files: dict[str, str],
        manifest: dict[str, Any] | None = None,
        context_parameters: list[dict[str, Any]] | None = None,
    ) -> dict[str, object]:
        ...

    def skill_editor_document(self, capability_id: str) -> dict[str, object]:
        ...

    def replace_skill_content(
        self,
        *,
        capability_id: str,
        expected_content_digest: str,
        metadata: dict[str, Any],
        instructions: str,
        resources: dict[str, str],
    ) -> dict[str, object]:
        ...


@dataclass(frozen=True, slots=True)
class DynamicRuntimeApiConfig:
    keepalive_seconds: float
    replay_limit: int
    managed_workspace_root: Path
    maximum_skill_file_bytes: int
    maximum_skill_bytes: int
    maximum_tool_file_bytes: int
    maximum_tool_bytes: int

    def __post_init__(self) -> None:
        if self.keepalive_seconds <= 0:
            raise ValueError("keepalive_seconds must be positive")
        if self.replay_limit < 1:
            raise ValueError("replay_limit must be positive")
        if self.maximum_skill_file_bytes < 1:
            raise ValueError("maximum_skill_file_bytes must be positive")
        if self.maximum_skill_bytes < self.maximum_skill_file_bytes:
            raise ValueError("maximum_skill_bytes must be at least maximum_skill_file_bytes")
        if self.maximum_tool_file_bytes < 1:
            raise ValueError("maximum_tool_file_bytes must be positive")
        if self.maximum_tool_bytes < self.maximum_tool_file_bytes:
            raise ValueError("maximum_tool_bytes must be at least maximum_tool_file_bytes")
        root = Path(self.managed_workspace_root).expanduser().resolve()
        object.__setattr__(self, "managed_workspace_root", root)


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
    execution_preference: str
    approval_mode: str
    model_profile_id: str
    reasoning_intensity: int | None = Field(default=None, ge=0)
    request_timeout_seconds: int = Field(ge=1)
    browser_operation_timeout_ms: int = Field(default=30_000, ge=1_000, le=600_000)
    browser_navigation_timeout_ms: int = Field(default=45_000, ge=1_000, le=600_000)
    max_model_attempts: int = Field(ge=1)
    max_parallel_temporary_agents: int = Field(ge=1)
    memory_auto_write_enabled: bool = True
    memory_write_interval_turns: int = Field(default=3, ge=1, le=1000)
    memory_agent_write_enabled: bool = True
    memory_max_injected_items: int = Field(default=8, ge=1, le=64)
    memory_max_injected_tokens: int = Field(default=1200, ge=100, le=32000)
    max_temporary_delegation_depth: int = Field(ge=0)
    delegation_grant_ttl_seconds: int = Field(ge=1)
    timezone: str

    @field_validator("execution_preference")
    @classmethod
    def _execution_preference_is_supported(cls, value: str) -> str:
        if value not in {"react", "plan_and_execute"}:
            raise ValueError("unsupported execution_preference")
        return value

    @field_validator("approval_mode")
    @classmethod
    def _approval_mode_is_supported(cls, value: str) -> str:
        if value not in {"ask", "auto", "always_approval"}:
            raise ValueError("unsupported approval_mode")
        return value

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
    timeout_seconds: float = Field(gt=0, le=3600)
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

def create_dynamic_runtime_router(
    *,
    application: DynamicRuntimeApplication,
    supervisor: DynamicRuntimeSupervisor,
    broadcaster: RuntimeEventBroadcaster,
    principal_resolver: RequestPrincipalResolver,
    capability_pools: CapabilityPoolManager,
    config: DynamicRuntimeApiConfig,
) -> APIRouter:
    router = APIRouter(prefix="/api/runtime")

    @router.get("/capabilities")
    async def capabilities(request: Request) -> dict[str, object]:
        principal_resolver.resolve(request)
        return await asyncio.to_thread(capability_pools.capability_pool_snapshot)

    @router.get("/main-agent-capability-profile")
    async def main_agent_capability_profile(request: Request) -> dict[str, object]:
        principal_resolver.resolve(request)
        return await asyncio.to_thread(capability_pools.main_agent_capability_profile)

    @router.put("/main-agent-capability-profile")
    async def replace_main_agent_capability_profile(
        request: Request,
        payload: MainAgentCapabilityProfileWriteRequest,
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(
                capability_pools.replace_main_agent_capability_profile,
                expected_revision=payload.expected_revision,
                capability_ids=tuple(payload.capability_ids),
                mcp_server_ids=tuple(payload.mcp_server_ids),
            )
        except RuntimeError as exc:
            if str(exc) == "main_agent_capability_profile_revision_conflict":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/capabilities/skillhub/status")
    async def skillhub_status(request: Request) -> dict[str, Any]:
        principal_resolver.resolve(request)
        return await asyncio.to_thread(capability_pools.skillhub_status)

    @router.post("/capabilities/skillhub/search")
    async def search_skillhub(
        request: Request,
        payload: SkillHubSearchRequest,
    ) -> dict[str, Any]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(capability_pools.search_skillhub, payload.query)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/capabilities/skillhub/install")
    async def install_skillhub_skill(
        request: Request,
        payload: SkillHubInstallRequest,
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(
                capability_pools.install_skillhub_skill,
                payload.skill,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/capabilities/skills/import", status_code=201)
    async def import_skill_folder(
        request: Request,
        root_name: str = Form(...),
        relative_paths: str = Form(...),
        files: list[UploadFile] = File(...),
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            paths = _folder_upload_paths(relative_paths, expected_count=len(files), capability="Skill")
            normalized_root = _portable_folder_root_name(root_name, capability="Skill")
            with tempfile.TemporaryDirectory(prefix="combo-skill-upload-") as temporary:
                source = Path(temporary) / normalized_root
                source.mkdir()
                total_bytes = 0
                for upload, relative_path in zip(files, paths, strict=True):
                    destination = source / relative_path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    total_bytes += await _write_bounded_upload(
                        upload,
                        destination,
                        maximum_file_bytes=config.maximum_skill_file_bytes,
                    )
                    if total_bytes > config.maximum_skill_bytes:
                        raise ValueError("Skill content exceeds configured byte limit")
                return await asyncio.to_thread(capability_pools.import_skill_folder, str(source))
        except RuntimeError as exc:
            if str(exc) == "skill_already_exists":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail="skill_synchronization_failed") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/capabilities/tools", status_code=201)
    async def create_tool_package(
        request: Request,
        specification: str = Form(...),
        main_file: UploadFile = File(...),
        resource_paths: str = Form("[]"),
        resource_files: list[UploadFile] = File(default=[]),
    ) -> StreamingResponse:
        principal_resolver.resolve(request)
        try:
            payload = ToolPackageCreateRequest.model_validate_json(specification)
            with tempfile.TemporaryDirectory(prefix="combo-tool-main-") as temporary:
                destination = Path(temporary) / "main.py"
                await _write_bounded_upload(
                    main_file,
                    destination,
                    maximum_file_bytes=config.maximum_tool_file_bytes,
                    capability="ToolPackage main.py",
                )
                try:
                    main_source = destination.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError("main.py must be UTF-8 text") from exc
                paths = _folder_upload_paths(
                    resource_paths,
                    expected_count=len(resource_files),
                    capability="ToolPackage resource",
                )
                resource_contents: dict[str, bytes] = {}
                total_resource_bytes = 0
                for upload, relative_path in zip(resource_files, paths, strict=True):
                    content_path = Path(temporary) / "resources" / relative_path
                    content_path.parent.mkdir(parents=True, exist_ok=True)
                    total_resource_bytes += await _write_bounded_upload(
                        upload,
                        content_path,
                        maximum_file_bytes=config.maximum_tool_file_bytes,
                        capability="ToolPackage resource",
                    )
                    if total_resource_bytes > config.maximum_tool_bytes:
                        raise ValueError("ToolPackage resources exceed configured byte limit")
                    resource_contents[f"resources/{relative_path}"] = content_path.read_bytes()
            normalized_payload = payload.model_dump(mode="json")

            def run_create(report: Callable[[str, dict[str, Any]], None]) -> dict[str, object]:
                return capability_pools.create_tool_package(
                    normalized_payload,
                    main_source,
                    resource_files=resource_contents,
                    on_progress=report,
                )

            return _tool_preparation_response(run_create)
        except RuntimeError as exc:
            if str(exc) == "tool_already_exists":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/capabilities/tools/validate")
    async def validate_tool_package(
        request: Request,
        specification: str = Form(...),
        main_file: UploadFile = File(...),
        resource_paths: str = Form("[]"),
        resource_files: list[UploadFile] = File(default=[]),
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        temporary = Path(tempfile.mkdtemp(prefix="combo-tool-validate-upload-"))
        try:
            payload = ToolPackageCreateRequest.model_validate_json(specification)
            main_path = temporary / "main.py"
            await _write_bounded_upload(
                main_file,
                main_path,
                maximum_file_bytes=config.maximum_tool_file_bytes,
                capability="ToolPackage main.py",
            )
            main_source = main_path.read_text(encoding="utf-8")
            paths = _folder_upload_paths(
                resource_paths,
                expected_count=len(resource_files),
                capability="ToolPackage resource",
            )
            resource_contents: dict[str, bytes] = {}
            for upload, relative_path in zip(resource_files, paths, strict=True):
                destination = temporary / "resources" / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                await _write_bounded_upload(
                    upload,
                    destination,
                    maximum_file_bytes=config.maximum_tool_file_bytes,
                    capability="ToolPackage resource",
                )
                resource_contents[f"resources/{relative_path}"] = destination.read_bytes()
            return await asyncio.to_thread(
                capability_pools.validate_tool_package,
                payload.model_dump(mode="json"),
                main_source,
                resource_files=resource_contents,
            )
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="main.py must be UTF-8 text") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    @router.post("/capabilities/tools/transcribe")
    async def transcribe_tool_package(
        request: Request,
        script_file: UploadFile = File(...),
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            raw = await script_file.read()
            if len(raw) > config.maximum_tool_file_bytes:
                raise ValueError("Python script exceeds configured byte limit")
            source = raw.decode("utf-8")
            result = await asyncio.to_thread(
                capability_pools.transcribe_tool_source,
                source,
                filename=str(script_file.filename or "script.py"),
            )
            return result.model_dump(mode="json") if hasattr(result, "model_dump") else dict(result)
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="Python script must be UTF-8 text") from exc
        except RuntimeError as exc:
            status = 409 if str(exc) == "task_model_not_configured" else 502
            raise HTTPException(status_code=status, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/capabilities/mcp/probe")
    async def probe_mcp_server(
        request: Request,
        payload: MCPServerProbeRequest,
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(
                capability_pools.probe_mcp_server,
                payload.capability_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="mcp_probe_failed") from exc

    @router.post("/capabilities/mcp/resource")
    async def read_mcp_resource(
        request: Request,
        payload: MCPResourceReadRequest,
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(
                capability_pools.read_mcp_resource,
                payload.capability_id,
                payload.uri,
                payload.uri_template,
                payload.arguments,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="mcp_resource_read_failed") from exc

    @router.post("/capabilities/mcp/prompt")
    async def get_mcp_prompt(
        request: Request,
        payload: MCPPromptGetRequest,
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(
                capability_pools.get_mcp_prompt,
                payload.capability_id,
                payload.name,
                payload.arguments,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="mcp_prompt_get_failed") from exc

    @router.post("/capabilities/mcp", status_code=201)
    async def add_mcp_server(
        request: Request,
        payload: MCPServerCreateRequest,
    ) -> StreamingResponse:
        principal_resolver.resolve(request)
        normalized_payload = payload.registry_document()

        def run_add(report: Callable[[str, dict[str, Any]], None]) -> dict[str, object]:
            return capability_pools.add_mcp_server(
                normalized_payload,
                expected_registry_digest=payload.expected_registry_digest,
                on_progress=report,
            )

        return _tool_preparation_response(run_add)

    @router.put("/capabilities/mcp/{server_id}")
    async def update_mcp_server(
        server_id: str,
        request: Request,
        payload: MCPServerCreateRequest,
    ) -> StreamingResponse:
        principal_resolver.resolve(request)
        normalized_payload = payload.registry_document()

        def run_replace(report: Callable[[str, dict[str, Any]], None]) -> dict[str, object]:
            return capability_pools.replace_mcp_server(
                server_id,
                normalized_payload,
                expected_registry_digest=payload.expected_registry_digest,
                on_progress=report,
            )

        return _tool_preparation_response(run_replace)

    @router.delete("/capabilities/mcp/{server_id}")
    async def delete_mcp_server(
        server_id: str,
        request: Request,
        expected_registry_digest: str,
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(
                capability_pools.delete_mcp_server,
                server_id,
                expected_registry_digest=expected_registry_digest,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            if str(exc) == "mcp_registry_revision_conflict":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail="mcp_discovery_failed") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.put("/capabilities/skills")
    async def update_skill(
        request: Request,
        payload: SkillReplaceRequest,
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(
                capability_pools.replace_skill,
                capability_id=payload.capability_id,
                source_path=payload.source_path,
                expected_content_digest=payload.expected_content_digest,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            if str(exc) == "skill_revision_conflict":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail="skill_synchronization_failed") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete("/capabilities/skills/{capability_id:path}")
    async def delete_skill(
        capability_id: str,
        request: Request,
        expected_content_digest: str,
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(
                capability_pools.delete_skill,
                capability_id,
                expected_content_digest=expected_content_digest,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            if str(exc) == "skill_revision_conflict":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail="skill_synchronization_failed") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.put("/capabilities/tools/{capability_id:path}")
    async def update_tool_configuration(
        capability_id: str,
        request: Request,
        payload: ToolConfigurationWriteRequest,
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(
                capability_pools.replace_tool_configuration,
                capability_id=capability_id,
                expected_content_digest=payload.expected_content_digest,
                display_name=payload.display_name,
                description=payload.description,
                runtime_policy=payload.runtime_policy.model_dump(mode="json"),
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            if str(exc) == "tool_revision_conflict":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail="tool_synchronization_failed") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete("/capabilities/tools/{capability_id:path}")
    async def delete_tool_package(
        capability_id: str,
        request: Request,
        expected_content_digest: str,
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(
                capability_pools.delete_tool_package,
                capability_id,
                expected_content_digest=expected_content_digest,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            if str(exc) == "tool_revision_conflict":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail="tool_synchronization_failed") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/capabilities/tool-packages/{capability_id:path}/editor")
    async def get_tool_package_editor(capability_id: str, request: Request) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(capability_pools.tool_package_editor_document, capability_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.put("/capabilities/tool-packages/{capability_id:path}/editor")
    async def update_tool_package_content(
        capability_id: str,
        request: Request,
        payload: ToolPackageContentWriteRequest,
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(
                capability_pools.replace_tool_package_content,
                capability_id=capability_id,
                expected_content_digest=payload.expected_content_digest,
                files=payload.files,
                manifest=payload.manifest,
                context_parameters=(
                    [item.model_dump(mode="json") for item in payload.context_parameters]
                    if payload.context_parameters is not None
                    else None
                ),
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            if str(exc) == "tool_revision_conflict":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/capabilities/skills/{capability_id:path}/editor")
    async def get_skill_editor(capability_id: str, request: Request) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(capability_pools.skill_editor_document, capability_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.put("/capabilities/skills/{capability_id:path}/editor")
    async def update_skill_content(
        capability_id: str,
        request: Request,
        payload: SkillContentWriteRequest,
    ) -> dict[str, object]:
        principal_resolver.resolve(request)
        try:
            return await asyncio.to_thread(
                capability_pools.replace_skill_content,
                capability_id=capability_id,
                expected_content_digest=payload.expected_content_digest,
                metadata=payload.metadata,
                instructions=payload.instructions,
                resources=payload.resources,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            if str(exc) == "skill_revision_conflict":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail="skill_synchronization_failed") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/conversations")
    async def list_conversations(request: Request) -> dict[str, object]:
        principal_id = principal_resolver.resolve(request)
        return {
            "conversations": [
                asdict(item)
                for item in application.stores.conversations.list_for_principal(principal_id)
            ]
        }

    @router.post("/conversations", status_code=201)
    async def create_conversation(
        request: Request,
        payload: ConversationCreateRequest,
    ) -> dict[str, object]:
        principal_id = principal_resolver.resolve(request)
        session_id = uuid4().hex
        workspace_id = uuid4().hex
        workspace_path = config.managed_workspace_root / workspace_id
        workspace_path.mkdir(parents=True, exist_ok=False)
        store = application.stores.conversations
        try:
            store.create_managed_conversation(
                session_id=session_id,
                workspace_id=workspace_id,
                principal_id=principal_id,
                managed_path=str(workspace_path),
                title=payload.title,
            )
        except Exception:
            workspace_path.rmdir()
            raise
        identity = store.require_identity(session_id)
        return {"conversation": asdict(identity), "title": payload.title}

    @router.get("/conversations/{session_id}")
    async def conversation(request: Request, session_id: str) -> dict[str, object]:
        principal_id = principal_resolver.resolve(request)
        identity = application.stores.conversations.require_identity(session_id)
        if identity.principal_id != principal_id:
            raise HTTPException(status_code=404, detail="conversation not found")
        return {
            "conversation": asdict(identity),
            "messages": [
                item.model_dump(mode="json")
                for item in application.stores.conversations.messages(session_id)
            ],
        }

    @router.post("/handshake", response_model=RuntimeProtocolHandshakeResult)
    async def handshake(payload: RuntimeProtocolHandshake) -> RuntimeProtocolHandshakeResult:
        server = _server_descriptor(application)
        accepted = server.matches(payload.client)
        return RuntimeProtocolHandshakeResult(
            status="accepted" if accepted else "incompatible",
            server=server,
            client_instance_id=payload.client_instance_id,
            error_code=None if accepted else "runtime_protocol_mismatch",
        )

    @router.get("/policy", response_model=UserRuntimePolicy)
    async def runtime_policy(request: Request) -> UserRuntimePolicy:
        principal_id = principal_resolver.resolve(request)
        try:
            return application.stores.runtime_policies.require_for_principal(principal_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="runtime_policy_not_configured") from exc

    @router.put("/policy", response_model=UserRuntimePolicy)
    async def write_runtime_policy(
        request: Request,
        payload: RuntimePolicyWriteRequest,
    ) -> UserRuntimePolicy:
        principal_id = principal_resolver.resolve(request)
        now = utc_now_text()
        try:
            current = application.stores.runtime_policies.require_for_principal(principal_id)
        except LookupError:
            current = None
        policy = UserRuntimePolicy(
            principal_id=principal_id,
            policy_id=current.policy_id if current is not None else uuid4().hex,
            revision=current.revision + 1 if current is not None else 1,
            execution_preference=payload.execution_preference,
            approval_mode=payload.approval_mode,
            model_profile_id=payload.model_profile_id,
            reasoning_intensity=payload.reasoning_intensity,
            request_timeout_seconds=payload.request_timeout_seconds,
            browser_operation_timeout_ms=payload.browser_operation_timeout_ms,
            browser_navigation_timeout_ms=payload.browser_navigation_timeout_ms,
            max_model_attempts=payload.max_model_attempts,
            max_parallel_temporary_agents=payload.max_parallel_temporary_agents,
            memory_auto_write_enabled=payload.memory_auto_write_enabled,
            memory_write_interval_turns=payload.memory_write_interval_turns,
            memory_agent_write_enabled=payload.memory_agent_write_enabled,
            memory_max_injected_items=payload.memory_max_injected_items,
            memory_max_injected_tokens=payload.memory_max_injected_tokens,
            max_temporary_delegation_depth=payload.max_temporary_delegation_depth,
            delegation_grant_ttl_seconds=payload.delegation_grant_ttl_seconds,
            timezone=payload.timezone,
            updated_at=now,
        )
        if current is None:
            if payload.expected_revision is not None:
                raise HTTPException(status_code=409, detail="runtime_policy_revision_conflict")
            saved = application.stores.runtime_policies.create(policy, created_at=now)
        else:
            if payload.expected_revision != current.revision:
                raise HTTPException(status_code=409, detail="runtime_policy_revision_conflict")
            saved = application.stores.runtime_policies.replace(
                policy,
                expected_revision=current.revision,
            )
        supervisor.notify_outbox()
        return saved

    @router.post("/commands", response_model=CommandReceipt)
    async def submit_command(
        request: Request,
        envelope: CommandEnvelope,
        x_combo_protocol: str = Header(alias="X-Combo-Protocol"),
        x_combo_schema: str = Header(alias="X-Combo-Schema"),
        x_combo_build: str = Header(alias="X-Combo-Build"),
    ) -> CommandReceipt:
        _require_compatible_headers(
            application,
            protocol_version=x_combo_protocol,
            schema_version=x_combo_schema,
            build_revision=x_combo_build,
        )
        principal_id = principal_resolver.resolve(request)
        if envelope.principal_id != principal_id:
            raise HTTPException(status_code=403, detail="command principal does not match authenticated principal")
        if envelope.protocol_version != x_combo_protocol:
            raise HTTPException(status_code=409, detail="runtime_protocol_mismatch")
        identity = application.stores.conversations.require_identity(envelope.session_id)
        if identity.principal_id != principal_id:
            raise HTTPException(status_code=403, detail="conversation is owned by a different principal")
        receipt = application.stores.commands.accept(
            envelope,
            CommandReceipt(
                command_id=envelope.command_id,
                client_instance_id=envelope.client_instance_id,
                principal_id=envelope.principal_id,
                session_id=envelope.session_id,
                status="received",
            ),
        )
        supervisor.notify_commands()
        supervisor.notify_outbox()
        return receipt

    @router.get("/commands/{command_id}", response_model=CommandReceipt)
    async def command_receipt(request: Request, command_id: str) -> CommandReceipt:
        principal_id = principal_resolver.resolve(request)
        receipt = application.stores.commands.get_receipt(command_id)
        if receipt.principal_id != principal_id:
            raise HTTPException(status_code=404, detail="command receipt not found")
        return receipt

    @router.get("/events")
    async def runtime_events(
        request: Request,
        session_id: str,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        principal_id = principal_resolver.resolve(request)
        identity = application.stores.conversations.require_identity(session_id)
        if identity.principal_id != principal_id:
            raise HTTPException(status_code=404, detail="conversation not found")
        subscription = await broadcaster.subscribe(session_id)
        try:
            replay_sequence = application.stores.runtime_events.session_sequence_for_event(
                session_id=session_id,
                event_id=last_event_id,
            )
            replay_high_water = application.stores.runtime_events.latest_session_sequence(session_id)
        except LookupError as exc:
            await broadcaster.unsubscribe(subscription)
            raise HTTPException(status_code=409, detail="runtime_event_cursor_unknown") from exc

        async def stream():
            delivered_sequence = replay_sequence
            try:
                while delivered_sequence < replay_high_water:
                    replay = application.stores.runtime_events.after_session_sequence(
                        session_id=session_id,
                        session_sequence=delivered_sequence,
                        limit=config.replay_limit,
                    )
                    if not replay:
                        yield _sse_control("runtime_event_gap")
                        return
                    for event in replay:
                        if event.session_sequence <= delivered_sequence:
                            continue
                        delivered_sequence = event.session_sequence
                        yield _sse_event(event.event_id, event.model_dump(mode="json"))
                while not await request.is_disconnected():
                    queue_task = asyncio.create_task(subscription.queue.get())
                    disconnect_task = asyncio.create_task(subscription.disconnected.wait())
                    done, pending = await asyncio.wait(
                        {queue_task, disconnect_task},
                        timeout=config.keepalive_seconds,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    if not done:
                        yield ": keep-alive\n\n"
                        continue
                    if disconnect_task in done and disconnect_task.result():
                        yield _sse_control(subscription.disconnect_reason or "stream_disconnected")
                        return
                    event = queue_task.result()
                    if event.session_sequence <= delivered_sequence:
                        continue
                    while delivered_sequence < event.session_sequence:
                        recovered = application.stores.runtime_events.after_session_sequence(
                            session_id=session_id,
                            session_sequence=delivered_sequence,
                            limit=config.replay_limit,
                        )
                        if not recovered:
                            yield _sse_control("runtime_event_gap")
                            return
                        for recovered_event in recovered:
                            if recovered_event.session_sequence <= delivered_sequence:
                                continue
                            delivered_sequence = recovered_event.session_sequence
                            yield _sse_event(
                                recovered_event.event_id,
                                recovered_event.model_dump(mode="json"),
                            )
            finally:
                await broadcaster.unsubscribe(subscription)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router


ToolProgressCallback = Callable[[str, dict[str, Any]], None]
ToolPreparationOperation = Callable[[ToolProgressCallback], dict[str, object]]


def _tool_preparation_response(operation: ToolPreparationOperation) -> StreamingResponse:
    async def stream():
        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=256)

        def report(stage: str, detail: dict[str, Any]) -> None:
            event = {"type": "progress", "stage": stage, "detail": detail}

            def enqueue() -> None:
                if progress_queue.full():
                    try:
                        progress_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                progress_queue.put_nowait(event)

            loop.call_soon_threadsafe(enqueue)

        worker = asyncio.create_task(asyncio.to_thread(operation, report))
        while not worker.done() or not progress_queue.empty():
            try:
                event = await asyncio.wait_for(progress_queue.get(), timeout=0.15)
            except TimeoutError:
                continue
            yield _ndjson_line(event)

        try:
            snapshot = worker.result()
        except Exception as exc:
            yield _ndjson_line({
                "type": "failed",
                "error": redact_sensitive_text(exception_summary(exc)),
            })
            return
        yield _ndjson_line({"type": "completed", "result": snapshot})

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _ndjson_line(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _folder_upload_paths(raw: str, *, expected_count: int, capability: str) -> tuple[Path, ...]:
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{capability} relative_paths must be valid JSON") from exc
    if not isinstance(values, list) or len(values) != expected_count:
        raise ValueError(f"{capability} relative_paths must correspond to uploaded files")
    paths: list[Path] = []
    portable: set[str] = set()
    for value in values:
        text = str(value or "").replace("\\", "/").strip("/")
        path = Path(text)
        if not text or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(f"{capability} upload path is invalid: {value}")
        key = path.as_posix().casefold()
        if key in portable:
            raise ValueError(f"{capability} upload contains a cross-platform path collision: {value}")
        portable.add(key)
        paths.append(path)
    return tuple(paths)


def _portable_folder_root_name(value: str, *, capability: str) -> str:
    name = str(value or "").strip()
    if not name or name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError(f"{capability} folder name is invalid")
    return name


async def _write_bounded_upload(
    upload: UploadFile,
    destination: Path,
    *,
    maximum_file_bytes: int,
    capability: str = "Skill",
) -> int:
    written = 0
    with destination.open("xb") as stream:
        while chunk := await upload.read(1024 * 1024):
            written += len(chunk)
            if written > maximum_file_bytes:
                raise ValueError(f"{capability} file exceeds configured byte limit: {destination.name}")
            stream.write(chunk)
    return written


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


def _server_descriptor(application: DynamicRuntimeApplication) -> RuntimeProtocolDescriptor:
    return RuntimeProtocolDescriptor(
        build_revision=application.config.build_revision,
    )


def _require_compatible_headers(
    application: DynamicRuntimeApplication,
    *,
    protocol_version: str,
    schema_version: str,
    build_revision: str,
) -> None:
    descriptor = _server_descriptor(application)
    if (
        protocol_version != descriptor.protocol_version
        or schema_version != descriptor.schema_version
        or build_revision != descriptor.build_revision
    ):
        raise HTTPException(status_code=409, detail="runtime_protocol_mismatch")


def _sse_event(event_id: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: runtime_event\ndata: {data}\n\n"


def _sse_control(reason: str) -> str:
    data = json.dumps({"reason": reason}, ensure_ascii=False, separators=(",", ":"))
    return f"event: stream_control\ndata: {data}\n\n"
