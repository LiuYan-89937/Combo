from __future__ import annotations

from hashlib import sha256
import json
import re
from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from agent_factory.runtime_protocol.contracts import FrozenProtocolModel


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MODEL_ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

CapabilityPlatform = Literal["any", "macos-arm64", "windows-x86_64", "linux-x86_64"]
ToolApprovalAction = Literal["inherit", "allow", "ask", "deny"]
ToolRiskLevel = Literal["low", "medium", "high"]
ToolEffect = Literal["read", "write", "delete", "process", "network", "credential", "external_side_effect"]
RuntimeResourceName = Literal[
    "filesystem",
    "process_runtime",
    "runtime_identity",
    "browser_runtime",
    "knowledge_runtime",
    "scheduler_runtime",
]


class SkillContentRef(FrozenProtocolModel):
    logical_path: str
    kind: Literal["reference", "template", "example", "asset", "script"]
    media_type: str
    blob_id: str
    content_digest: str
    size_bytes: int = Field(ge=0)

    @field_validator("logical_path", "media_type", "blob_id")
    @classmethod
    def _required_text(cls, value: str, info: object) -> str:
        return _required_text(value, getattr(info, "field_name", "value"))

    @field_validator("content_digest")
    @classmethod
    def _digest_is_sha256(cls, value: str) -> str:
        return _sha256_text(value, "skill content digest")

    @field_validator("logical_path")
    @classmethod
    def _path_is_logical(cls, value: str) -> str:
        text = value.replace("\\", "/")
        if text.startswith("/") or any(part in {"", ".", ".."} for part in text.split("/")):
            raise ValueError("skill logical_path must be a normalized relative path")
        return text


class SkillDefinition(FrozenProtocolModel):
    schema_version: Literal["skill_definition.v1"] = "skill_definition.v1"
    instructions: str
    contents: tuple[SkillContentRef, ...] = ()

    @field_validator("instructions")
    @classmethod
    def _instructions_are_present(cls, value: str) -> str:
        return _required_text(value, "skill instructions")

    @model_validator(mode="after")
    def _content_paths_are_unique(self) -> "SkillDefinition":
        paths = [item.logical_path for item in self.contents]
        if len(paths) != len(set(paths)):
            raise ValueError("skill content logical paths must be unique")
        return self


class ToolImplementation(FrozenProtocolModel):
    kind: Literal["python_module", "python_source", "managed_process"]
    entrypoint: str
    source_blob_id: str | None = None
    source_digest: str | None = None

    @field_validator("entrypoint")
    @classmethod
    def _entrypoint_is_present(cls, value: str) -> str:
        text = _required_text(value, "tool entrypoint")
        if ":" not in text:
            raise ValueError("tool entrypoint must identify an adapter target and callable")
        return text

    @field_validator("source_blob_id")
    @classmethod
    def _optional_blob_id(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("source_digest")
    @classmethod
    def _optional_source_digest(cls, value: str | None) -> str | None:
        return None if value is None else _sha256_text(value, "tool source digest")

    @model_validator(mode="after")
    def _source_kind_matches_reference(self) -> "ToolImplementation":
        has_source = self.source_blob_id is not None and self.source_digest is not None
        if self.kind == "python_source" and not has_source:
            raise ValueError("python_source implementation requires source blob and digest")
        if self.kind != "python_source" and (self.source_blob_id is not None or self.source_digest is not None):
            raise ValueError("only python_source implementation may carry source blob fields")
        return self


class ToolRuntimePolicy(FrozenProtocolModel):
    approval: ToolApprovalAction = "inherit"
    risk_level: ToolRiskLevel = "low"
    allow_parallel_calls: bool = True
    serialization_key: str | None = None
    timeout_seconds: float = Field(default=300.0, gt=0)
    output_projection: Literal["compress", "passthrough"] = "compress"
    output_max_model_chars: int = Field(default=50_000, ge=1_000, le=1_000_000)
    retain_raw_output: bool = True

    @field_validator("serialization_key")
    @classmethod
    def _optional_serialization_key(cls, value: str | None) -> str | None:
        return _optional_text(value)


class ToolResourceBinding(FrozenProtocolModel):
    name: str
    resource_id: str
    resource_revision: int = Field(ge=1)
    purpose: str

    @field_validator("name", "resource_id", "purpose")
    @classmethod
    def _binding_text_is_present(cls, value: str, info: object) -> str:
        return _required_text(value, getattr(info, "field_name", "value"))


class ToolDefinition(FrozenProtocolModel):
    schema_version: Literal["tool_definition.v1"] = "tool_definition.v1"
    model_alias: str
    model_description: str
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    implementation: ToolImplementation
    runtime_policy: ToolRuntimePolicy = Field(default_factory=ToolRuntimePolicy)
    resource_bindings: tuple[ToolResourceBinding, ...] = ()
    runtime_resources: tuple[RuntimeResourceName, ...] = ()
    effects: tuple[ToolEffect, ...]
    read_only: bool = False
    system_available: bool = False
    required_input_modalities: tuple[Literal["text", "image", "audio", "video"], ...] = ("text",)
    output_modalities: tuple[Literal["text", "image", "audio", "video", "file", "structured"], ...] = (
        "structured",
    )
    platforms: tuple[CapabilityPlatform, ...] = ("any",)
    sensitive_argument_paths: tuple[str, ...] = ()

    @field_validator("model_alias")
    @classmethod
    def _model_alias_is_stable(cls, value: str) -> str:
        text = _required_text(value, "tool model_alias")
        if not MODEL_ALIAS_PATTERN.fullmatch(text):
            raise ValueError("tool model_alias must be lowercase snake_case and at most 64 characters")
        return text

    @field_validator("model_description")
    @classmethod
    def _description_is_present(cls, value: str) -> str:
        return _required_text(value, "tool model_description")

    @field_validator("effects", "runtime_resources", "required_input_modalities", "output_modalities", "platforms")
    @classmethod
    def _tuple_values_are_unique(cls, values: tuple[str, ...], info: object) -> tuple[str, ...]:
        if not values:
            raise ValueError(f"{getattr(info, 'field_name', 'values')} must not be empty")
        if len(values) != len(set(values)):
            raise ValueError(f"{getattr(info, 'field_name', 'values')} must be unique")
        if "any" in values and len(values) > 1:
            raise ValueError("platform 'any' cannot be combined with concrete platforms")
        return values

    @field_validator("sensitive_argument_paths")
    @classmethod
    def _sensitive_paths_are_json_pointers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)) or any(not value.startswith("/") for value in values):
            raise ValueError("sensitive_argument_paths must be unique JSON Pointers")
        return values

    @model_validator(mode="after")
    def _read_only_matches_effects(self) -> "ToolDefinition":
        mutating = {"write", "delete", "process", "network", "credential", "external_side_effect"}
        if self.read_only and mutating.intersection(self.effects):
            raise ValueError("read-only tool cannot declare mutating effects")
        binding_names = [item.name for item in self.resource_bindings]
        if len(binding_names) != len(set(binding_names)):
            raise ValueError("tool resource binding names must be unique")
        return self


class MCPResourceBinding(FrozenProtocolModel):
    target: Literal["environment", "header"]
    name: str
    resource_id: str
    resource_revision: int = Field(ge=1)
    purpose: str

    @field_validator("name", "resource_id", "purpose")
    @classmethod
    def _binding_text_is_present(cls, value: str, info: object) -> str:
        return _required_text(value, getattr(info, "field_name", "value"))


class MCPServerDefinition(FrozenProtocolModel):
    schema_version: Literal["mcp_server_definition.v1"] = "mcp_server_definition.v1"
    transport: Literal["stdio", "streamable_http", "sse"]
    executable: str | None = None
    arguments: tuple[str, ...] = ()
    endpoint: str | None = None
    working_directory_alias: str | None = None
    resource_bindings: tuple[MCPResourceBinding, ...] = ()
    connect_timeout_seconds: float = Field(default=30.0, gt=0)
    request_timeout_seconds: float = Field(default=120.0, gt=0)
    max_parallel_requests: int = Field(default=1, ge=1)

    @field_validator("executable", "endpoint", "working_directory_alias")
    @classmethod
    def _optional_server_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("arguments")
    @classmethod
    def _arguments_are_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(str(value) for value in values)

    @model_validator(mode="after")
    def _transport_fields_match(self) -> "MCPServerDefinition":
        if self.transport == "stdio":
            if self.executable is None or self.endpoint is not None:
                raise ValueError("stdio MCP server requires executable and forbids endpoint")
        elif self.endpoint is None or self.executable is not None or self.arguments:
            raise ValueError("HTTP MCP server requires endpoint and forbids executable arguments")
        binding_keys = [(item.target, item.name.casefold()) for item in self.resource_bindings]
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("MCP resource binding targets and names must be unique")
        return self


class MCPSchemaRepairRecord(FrozenProtocolModel):
    path: str
    original_digest: str
    replacement_digest: str
    reason: str

    @field_validator("path", "reason")
    @classmethod
    def _repair_text_is_present(cls, value: str, info: object) -> str:
        return _required_text(value, getattr(info, "field_name", "value"))

    @field_validator("original_digest", "replacement_digest")
    @classmethod
    def _repair_digest_is_sha256(cls, value: str, info: object) -> str:
        return _sha256_text(value, getattr(info, "field_name", "digest"))


class MCPProviderSchemaProjection(FrozenProtocolModel):
    provider_id: str
    projected_schema: dict[str, JsonValue]
    schema_digest: str

    @field_validator("provider_id")
    @classmethod
    def _provider_id_is_present(cls, value: str) -> str:
        return _required_text(value, "provider_id")

    @model_validator(mode="after")
    def _projection_digest_matches(self) -> "MCPProviderSchemaProjection":
        if self.schema_digest != _json_digest(self.projected_schema):
            raise ValueError("MCP provider schema projection digest does not match schema")
        return self


class MCPSchemaEvidence(FrozenProtocolModel):
    dialect: Literal["draft_2020_12", "draft_2019_09", "draft_07", "mcp_unspecified"]
    source_schema: dict[str, JsonValue]
    source_digest: str
    normalization_receipt: tuple[MCPSchemaRepairRecord, ...] = ()
    canonical_schema: dict[str, JsonValue]
    canonical_digest: str
    provider_projections: tuple[MCPProviderSchemaProjection, ...] = ()

    @model_validator(mode="after")
    def _schema_digests_match(self) -> "MCPSchemaEvidence":
        if self.source_digest != _json_digest(self.source_schema):
            raise ValueError("MCP source schema digest does not match schema")
        if self.canonical_digest != _json_digest(self.canonical_schema):
            raise ValueError("MCP canonical schema digest does not match schema")
        providers = [item.provider_id for item in self.provider_projections]
        if len(providers) != len(set(providers)):
            raise ValueError("MCP provider schema projections must use unique provider IDs")
        return self


class MCPToolDefinition(FrozenProtocolModel):
    schema_version: Literal["mcp_tool_definition.v1"] = "mcp_tool_definition.v1"
    server_capability_id: str
    upstream_tool_name: str
    model_alias: str
    model_description: str
    input_schema: MCPSchemaEvidence
    output_schema: MCPSchemaEvidence
    runtime_policy: ToolRuntimePolicy = Field(default_factory=lambda: ToolRuntimePolicy(risk_level="medium"))

    @field_validator("server_capability_id", "upstream_tool_name", "model_description")
    @classmethod
    def _tool_text_is_present(cls, value: str, info: object) -> str:
        return _required_text(value, getattr(info, "field_name", "value"))

    @field_validator("model_alias")
    @classmethod
    def _model_alias_is_stable(cls, value: str) -> str:
        text = _required_text(value, "MCP tool model_alias")
        if not MODEL_ALIAS_PATTERN.fullmatch(text):
            raise ValueError("MCP tool model_alias must be lowercase snake_case and at most 64 characters")
        return text


class DependencyArtifact(FrozenProtocolModel):
    artifact_id: str
    ecosystem: Literal["python", "npm", "executable"]
    name: str
    version: str
    source_uri: str
    artifact_digest: str
    filename: str
    dependencies: tuple[str, ...] = ()
    license_id: str | None = None

    @field_validator("artifact_id", "name", "version", "source_uri", "filename")
    @classmethod
    def _artifact_text_is_present(cls, value: str, info: object) -> str:
        return _required_text(value, getattr(info, "field_name", "value"))

    @field_validator("artifact_digest")
    @classmethod
    def _artifact_digest_is_sha256(cls, value: str) -> str:
        return _sha256_text(value, "dependency artifact digest")

    @field_validator("dependencies")
    @classmethod
    def _artifact_dependencies_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_required_text(value, "dependency artifact reference") for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("dependency artifact references must be unique")
        return normalized

    @field_validator("license_id")
    @classmethod
    def _optional_license(cls, value: str | None) -> str | None:
        return _optional_text(value)


class DependencyDefinition(FrozenProtocolModel):
    schema_version: Literal["dependency_definition.v1"] = "dependency_definition.v1"
    environment_id: str
    platform: CapabilityPlatform
    python_abi: str | None = None
    root_artifact_ids: tuple[str, ...]
    artifacts: tuple[DependencyArtifact, ...]
    resolved_graph_digest: str

    @field_validator("environment_id")
    @classmethod
    def _environment_id_is_present(cls, value: str) -> str:
        return _required_text(value, "dependency environment_id")

    @field_validator("python_abi")
    @classmethod
    def _optional_python_abi(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("resolved_graph_digest")
    @classmethod
    def _graph_digest_is_sha256(cls, value: str) -> str:
        return _sha256_text(value, "resolved dependency graph digest")

    @model_validator(mode="after")
    def _graph_is_closed_and_digest_matches(self) -> "DependencyDefinition":
        artifacts = {item.artifact_id: item for item in self.artifacts}
        if len(artifacts) != len(self.artifacts):
            raise ValueError("dependency artifact IDs must be unique")
        roots = tuple(_required_text(value, "root artifact ID") for value in self.root_artifact_ids)
        if not roots or len(roots) != len(set(roots)):
            raise ValueError("dependency root artifact IDs must be non-empty and unique")
        referenced = set(roots)
        for artifact in self.artifacts:
            referenced.update(artifact.dependencies)
        missing = sorted(referenced - set(artifacts))
        if missing:
            raise ValueError("dependency graph references unknown artifacts: " + ", ".join(missing))
        payload = {
            "platform": self.platform,
            "python_abi": self.python_abi,
            "root_artifact_ids": list(roots),
            "artifacts": [item.model_dump(mode="json") for item in sorted(self.artifacts, key=lambda item: item.artifact_id)],
        }
        if self.resolved_graph_digest != _json_digest(payload):
            raise ValueError("resolved dependency graph digest does not match graph")
        return self


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _optional_text(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _sha256_text(value: str, field_name: str) -> str:
    text = _required_text(value, field_name).lower()
    if not SHA256_PATTERN.fullmatch(text):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return text


def _json_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
