from __future__ import annotations

from pathlib import Path

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.registry import FilesystemRegistry, RegistryRecord


class RegisterAgentRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    package_path: Path
    status: str = "candidate"


class RegistryListResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    records: list[RegistryRecord] = Field(default_factory=list)


class RegistryService:
    def __init__(self, registry: FilesystemRegistry | None = None) -> None:
        self.registry = registry or FilesystemRegistry()

    def register(self, request: RegisterAgentRequest) -> RegistryRecord:
        return self.registry.register(request.package_path, status=request.status)  # type: ignore[arg-type]

    def list(self) -> RegistryListResult:
        return RegistryListResult(records=self.registry.list())

    def release(self, agent_name: str, version: str, status: str) -> RegistryRecord:
        return self.registry.release(agent_name, version, status)  # type: ignore[arg-type]

    def rollback(self, agent_name: str, version: str) -> RegistryRecord:
        return self.registry.rollback(agent_name, version)
