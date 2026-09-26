from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from combo.context_system.memory_results import MemorySearchResult
from combo.runtime_protocol.delegation_requests import (
    DelegationContinuationRequest,
    DelegationMessageRequest,
    DelegationRequest,
)
from combo.runtime_protocol.knowledge import KnowledgeDocumentRecord
from combo.runtime_protocol.memory import MemoryKind, MemoryRevision, MemoryScope


@runtime_checkable
class DelegationRuntimePort(Protocol):
    def delegate(self, request: DelegationRequest) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...

    def continue_task(self, request: DelegationContinuationRequest) -> dict[str, Any]: ...

    def message_task(self, request: DelegationMessageRequest) -> dict[str, Any]: ...


@runtime_checkable
class CapabilityCatalogPort(Protocol):
    def list_active(self) -> list[dict[str, object]]: ...

    def search(self, query: str, *, limit: int) -> list[dict[str, object]]: ...

    def search_mcp(
        self, server_name: str, query: str, *, kinds: tuple[str, ...], limit: int,
    ) -> list[dict[str, object]]: ...

    def describe(
        self, *, name: str, kind: str | None = None, server_name: str | None = None,
    ) -> dict[str, object]: ...


@runtime_checkable
class CapabilityInvocationPort(Protocol):
    def invoke(
        self, *, name: str, kind: str, server_name: str | None,
        arguments: dict[str, Any],
    ) -> dict[str, Any]: ...


@runtime_checkable
class SkillRuntimePort(Protocol):
    def list(self) -> list[dict[str, object]]: ...

    def describe(self, name: str) -> dict[str, object]: ...

    def load(self, name: str) -> dict[str, object]: ...

    def read_resource(self, name: str, *, path: str) -> dict[str, object]: ...


@runtime_checkable
class ImageGenerationRuntimePort(Protocol):
    def generate(self, arguments: dict[str, Any]) -> list[dict[str, Any]]: ...


@runtime_checkable
class MCPContentRuntimePort(Protocol):
    def read_resource(self, server_name: str, uri: str) -> dict[str, Any]: ...

    def get_prompt(
        self, server_name: str, name: str, arguments: dict[str, str],
    ) -> dict[str, Any]: ...


@runtime_checkable
class KnowledgeRuntimePort(Protocol):
    def sources(self) -> list[dict[str, Any]]: ...

    def search(self, *, query: str, limit: int | None = None, source_id: str | None = None) -> list[dict[str, Any]]: ...

    def documents(self, source_id: str) -> list[KnowledgeDocumentRecord]: ...

    def require_document(self, document_id: str) -> KnowledgeDocumentRecord: ...

    def create_source(self, payload: dict[str, Any], documents: list[dict[str, str]]) -> dict[str, Any]: ...

    def delete_source(self, source_id: str) -> None: ...


@runtime_checkable
class SchedulerRuntimePort(Protocol):
    def jobs(self, workspace_ids: tuple[str, ...]) -> list[dict[str, Any]]: ...

    def require_job(self, job_id: str) -> dict[str, Any]: ...

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def set_status(self, job_id: str, status: str) -> None: ...


@runtime_checkable
class MemoryRuntimePort(Protocol):
    def search(
        self, *, principal_id: str, workspace_id: str, query: str, limit: int,
        min_relevance: float = 0.0,
    ) -> tuple[MemorySearchResult, ...]: ...

    def write(
        self, *, principal_id: str, scope: MemoryScope, workspace_id: str | None,
        kind: MemoryKind, content: str, confidence: float,
        source_session_id: str, source_turn_id: str, runtime_instance_id: str,
    ) -> MemoryRevision: ...


@runtime_checkable
class CapabilityInstallerPort(Protocol):
    def install_skill(self, package: dict[str, Any]) -> dict[str, Any]: ...

    def install_mcp(self, config: object) -> dict[str, Any]: ...
