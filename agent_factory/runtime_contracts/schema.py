from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.context_system import ContextContractConfig
from agent_factory.memory_system import MemorySystemConfig, default_agent_memory_config
from agent_factory.scheduler_system.schema import SchedulerContractConfig


ContractType = Literal[
    "session",
    "tools",
    "memory",
    "render",
    "resources",
    "sandbox",
    "dependencies",
    "model",
    "scheduler",
    "context",
    "state",
    "node_provider",
    "artifact",
]
ContractVersion = Literal[
    "session_contract.v0",
    "tools_contract.v0",
    "memory_contract.v0",
    "render_contract.v0",
    "resources_contract.v0",
    "sandbox_contract.v0",
    "dependencies_contract.v0",
    "model_contract.v0",
    "scheduler_contract.v0",
    "context_contract.v0",
    "state_contract.v0",
    "node_provider_contract.v0",
    "artifact_contract.v0",
]
REQUIRED_AGENT_PACKAGE_CONTRACTS = frozenset(
    {
        "artifact",
        "context",
        "dependencies",
        "model",
        "node_provider",
        "render",
        "resources",
        "sandbox",
        "scheduler",
        "session",
        "state",
        "tools",
    }
)


class ContractValidationError(ValueError):
    pass


class AgentPackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["agent_package.v0"] = "agent_package.v0"
    factory_run_id: str
    agent: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)
    assembly_spec_path: str
    render_manifest_path: str
    resources_path: str
    sandbox_contract_path: str
    contracts: dict[str, str] = Field(default_factory=dict)
    bindings: dict[str, str] = Field(default_factory=dict)
    patterns: list[str] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    formatters: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_referenced_paths(self) -> "AgentPackageManifest":
        missing_contracts = sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS - set(self.contracts))
        if missing_contracts:
            raise ValueError("agent package missing required contracts: " + ", ".join(missing_contracts))
        for key in (
            "assembly_spec_path",
            "render_manifest_path",
            "resources_path",
            "sandbox_contract_path",
        ):
            _validate_package_relative_path(str(getattr(self, key)), field_name=key)
        for key, value in self.contracts.items():
            if not key.strip():
                raise ValueError("contracts keys must be non-empty")
            _validate_package_relative_path(value, field_name=f"contracts.{key}")
        for key, value in self.bindings.items():
            _validate_package_relative_path(value, field_name=f"bindings.{key}")
        for field_name in ("patterns", "prompts", "tools", "policies", "strategies", "formatters"):
            for value in getattr(self, field_name):
                _validate_package_relative_path(value, field_name=field_name)
        return self


class RuntimeContractEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    version: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class SessionContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_root: str = ".agent_runtime/sessions"
    checkpointer_backend: Literal["sqlite", "memory"] = "sqlite"
    checkpoint_path: str = ".agent_runtime/checkpoints/agent.sqlite"


class SessionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["session"] = "session"
    version: Literal["session_contract.v0"] = "session_contract.v0"
    enabled: bool = True
    config: SessionContractConfig = Field(default_factory=SessionContractConfig)


class ToolsContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    builtin_tools_enabled: bool = True
    builtin_tool_ids: list[str] = Field(default_factory=list)
    builtin_workspace_root: str = "/workdir"
    builtin_allow_external_paths: bool = False
    package_tools_enabled: bool = True
    instance_extensions_enabled: bool = True
    instance_extension_root: str = "/runtime/extensions"

    @field_validator("builtin_tool_ids")
    @classmethod
    def _builtin_tool_ids_are_not_empty(cls, value: list[str]) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for item in value:
            tool_id = str(item).strip()
            if not tool_id:
                raise ValueError("builtin_tool_ids must not contain empty ids")
            if tool_id not in seen:
                ids.append(tool_id)
                seen.add(tool_id)
        return ids

    @field_validator("builtin_workspace_root")
    @classmethod
    def _builtin_workspace_root_is_sandbox_absolute(cls, value: str) -> str:
        root = str(value).strip()
        if not root:
            raise ValueError("builtin_workspace_root must not be empty")
        path = PurePosixPath(root)
        if not path.is_absolute():
            raise ValueError("builtin_workspace_root must be an absolute sandbox path")
        if path == PurePosixPath("/"):
            raise ValueError("builtin_workspace_root must not be the container root")
        return root

    @field_validator("instance_extension_root")
    @classmethod
    def _extension_root_is_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("instance_extension_root must not be empty")
        return value


class ToolsContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tools"] = "tools"
    version: Literal["tools_contract.v0"] = "tools_contract.v0"
    enabled: bool = True
    config: ToolsContractConfig = Field(default_factory=ToolsContractConfig)


class MemoryContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_system: MemorySystemConfig = Field(default_factory=default_agent_memory_config)


class MemoryContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["memory"] = "memory"
    version: Literal["memory_contract.v0"] = "memory_contract.v0"
    enabled: bool = True
    config: MemoryContractConfig = Field(default_factory=MemoryContractConfig)


class ContextContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["context"] = "context"
    version: Literal["context_contract.v0"] = "context_contract.v0"
    enabled: bool = True
    config: ContextContractConfig = Field(default_factory=ContextContractConfig)


class ModelContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["main", "task"] = "main"
    source: Literal["factory_runtime_env"] = "factory_runtime_env"


class ModelContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["model"] = "model"
    version: Literal["model_contract.v0"] = "model_contract.v0"
    enabled: bool = True
    config: ModelContractConfig = Field(default_factory=ModelContractConfig)


class StateContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    namespace: str = "package"
    schema_path: str = "state/package.schema.json"
    initial_state_path: str = "state/package.initial.json"
    writable_node_ids: list[str] = Field(default_factory=list)

    @field_validator("namespace")
    @classmethod
    def _namespace_is_valid(cls, value: str) -> str:
        namespace = str(value).strip()
        if not namespace:
            raise ValueError("state namespace must not be empty")
        if not namespace.replace("_", "").replace(".", "").isalnum() or namespace[0].isdigit():
            raise ValueError("state namespace must use lowercase alphanumeric, underscore, and dot segments")
        for part in namespace.split("."):
            if not part or not part[0].isalpha() or part.lower() != part:
                raise ValueError("state namespace segments must start with a lowercase letter")
        return namespace

    @field_validator("schema_path", "initial_state_path")
    @classmethod
    def _state_paths_are_relative(cls, value: str) -> str:
        return _validate_package_relative_path(value, field_name="state contract path")

    @field_validator("writable_node_ids")
    @classmethod
    def _node_ids_are_non_empty(cls, value: list[str]) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for item in value:
            node_id = str(item).strip()
            if not node_id:
                raise ValueError("writable_node_ids must not contain empty values")
            if node_id not in seen:
                ids.append(node_id)
                seen.add(node_id)
        return ids


class StateContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["state"] = "state"
    version: Literal["state_contract.v0"] = "state_contract.v0"
    enabled: bool = False
    config: StateContractConfig = Field(default_factory=StateContractConfig)


class NodeProviderContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_ids: list[str] = Field(default_factory=list)

    @field_validator("provider_ids")
    @classmethod
    def _provider_ids_are_non_empty(cls, value: list[str]) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for item in value:
            provider_id = str(item).strip()
            if not provider_id:
                raise ValueError("provider_ids must not contain empty values")
            if provider_id not in seen:
                ids.append(provider_id)
                seen.add(provider_id)
        return ids


class NodeProviderContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["node_provider"] = "node_provider"
    version: Literal["node_provider_contract.v0"] = "node_provider_contract.v0"
    enabled: bool = True
    config: NodeProviderContractConfig = Field(default_factory=NodeProviderContractConfig)


class ArtifactContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = "/artifacts"
    index_path: str = "/artifacts/index.jsonl"
    allowed_kinds: list[str] = Field(default_factory=lambda: ["report", "artifact"])

    @field_validator("root", "index_path")
    @classmethod
    def _artifact_path_is_safe(cls, value: str) -> str:
        raw = str(value).strip()
        if not raw:
            raise ValueError("artifact paths must not be empty")
        path = PurePosixPath(raw)
        if path == PurePosixPath("/"):
            raise ValueError("artifact paths must not point at the container root")
        if any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("artifact paths must not contain empty, current, or parent segments")
        return raw

    @field_validator("allowed_kinds")
    @classmethod
    def _allowed_kinds_are_valid(cls, value: list[str]) -> list[str]:
        kinds: list[str] = []
        seen: set[str] = set()
        for item in value:
            kind = str(item).strip()
            if not kind:
                raise ValueError("allowed_kinds must not contain empty values")
            if "/" in kind or ".." in kind:
                raise ValueError("artifact kind must be a simple identifier")
            if kind not in seen:
                kinds.append(kind)
                seen.add(kind)
        if not kinds:
            raise ValueError("allowed_kinds must not be empty")
        return kinds


class ArtifactContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["artifact"] = "artifact"
    version: Literal["artifact_contract.v0"] = "artifact_contract.v0"
    enabled: bool = True
    config: ArtifactContractConfig = Field(default_factory=ArtifactContractConfig)


class RenderContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_path: str = "render_manifest.json"

    @field_validator("manifest_path")
    @classmethod
    def _path_is_relative(cls, value: str) -> str:
        return _validate_package_relative_path(value, field_name="manifest_path")


class RenderContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["render"] = "render"
    version: Literal["render_contract.v0"] = "render_contract.v0"
    enabled: bool = True
    config: RenderContractConfig = Field(default_factory=RenderContractConfig)


class ResourcesContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resources_path: str = "resources.json"

    @field_validator("resources_path")
    @classmethod
    def _path_is_relative(cls, value: str) -> str:
        return _validate_package_relative_path(value, field_name="resources_path")


class ResourcesContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["resources"] = "resources"
    version: Literal["resources_contract.v0"] = "resources_contract.v0"
    enabled: bool = True
    config: ResourcesContractConfig = Field(default_factory=ResourcesContractConfig)


class SandboxRuntimeContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sandbox_contract_path: str = "sandbox_contract.json"

    @field_validator("sandbox_contract_path")
    @classmethod
    def _path_is_relative(cls, value: str) -> str:
        return _validate_package_relative_path(value, field_name="sandbox_contract_path")


class SandboxRuntimeContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["sandbox"] = "sandbox"
    version: Literal["sandbox_contract.v0"] = "sandbox_contract.v0"
    enabled: bool = True
    config: SandboxRuntimeContractConfig = Field(default_factory=SandboxRuntimeContractConfig)


class DependenciesContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    python_requirements: list[str] = Field(default_factory=list)
    system_packages: list[str] = Field(default_factory=list)
    system_binaries: list[str] = Field(default_factory=list)
    install_mode: Literal["none", "sandbox_init"] = "sandbox_init"


class DependenciesContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["dependencies"] = "dependencies"
    version: Literal["dependencies_contract.v0"] = "dependencies_contract.v0"
    enabled: bool = True
    config: DependenciesContractConfig = Field(default_factory=DependenciesContractConfig)


class SchedulerContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["scheduler"] = "scheduler"
    version: Literal["scheduler_contract.v0"] = "scheduler_contract.v0"
    enabled: bool = True
    config: SchedulerContractConfig = Field(default_factory=SchedulerContractConfig)


RuntimeContract = (
    SessionContract
    | ToolsContract
    | MemoryContract
    | ContextContract
    | RenderContract
    | ResourcesContract
    | SandboxRuntimeContract
    | DependenciesContract
    | ModelContract
    | SchedulerContract
    | StateContract
    | NodeProviderContract
    | ArtifactContract
)


def _validate_package_relative_path(value: str, *, field_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise ValueError(f"{field_name} must be relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field_name} must not contain empty, current, or parent segments")
    return value
