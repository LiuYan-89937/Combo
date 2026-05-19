from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.memory_system import MemorySystemConfig, default_agent_memory_config


ContractType = Literal["session", "tools", "memory", "render", "resources", "sandbox"]
ContractVersion = Literal[
    "session_contract.v0",
    "tools_contract.v0",
    "memory_contract.v0",
    "render_contract.v0",
    "resources_contract.v0",
    "sandbox_contract.v0",
]


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
    prompts: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    policies: list[str] = Field(default_factory=list)
    strategy_profiles: list[str] = Field(default_factory=list)
    formatters: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_referenced_paths(self) -> "AgentPackageManifest":
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
        for field_name in ("prompts", "tools", "policies", "strategy_profiles", "formatters"):
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

    package_tools_enabled: bool = True
    instance_extensions_enabled: bool = True
    instance_extension_root: str = ".agent_runtime/extensions"

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


RuntimeContract = (
    SessionContract
    | ToolsContract
    | MemoryContract
    | RenderContract
    | ResourcesContract
    | SandboxRuntimeContract
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
