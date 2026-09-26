from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.store.base import BaseStore
from pydantic import BaseModel, ConfigDict

from combo.context_system.runtime import ContextSystemRuntime
from combo.runtime_kernel.context.engine import ContextEngine
from combo.runtime_kernel.errors import RuntimeKernelError
from combo.runtime_kernel.model_operations.service import ModelOperationService
from combo.runtime_kernel.observability.emitter import ObservabilityManager


@runtime_checkable
class RuntimeToolRegistry(Protocol):
    def list_tool_ids(self) -> list[str]: ...

    def model_tools(self, tool_ids: list[str] | set[str] | None = None) -> list[BaseTool]: ...


@runtime_checkable
class RuntimeContextResourceReader(Protocol):
    def current(self) -> Mapping[str, Any]: ...


class RuntimeServices(BaseModel):
    """Application-owned dependencies shared by the two fixed runtime graphs."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    model_operation_service: ModelOperationService
    tool_registry: RuntimeToolRegistry
    graph_store: BaseStore
    context_system: ContextSystemRuntime
    context_engine: ContextEngine
    observability_manager: ObservabilityManager
    checkpointer: BaseCheckpointSaver
    scheduler_store: object | None = None
    scheduler_runtime: object | None = None
    artifact_store: object | None = None
    runtime_context_resources: RuntimeContextResourceReader

    def get_required(self, name: str) -> Any:
        value = getattr(self, name, None)
        if value is None:
            raise RuntimeKernelError(f"Missing required runtime service: {name}")
        return value

    def validate_required(self, service_names: list[str]) -> None:
        missing = [name for name in service_names if getattr(self, name, None) is None]
        if missing:
            raise RuntimeKernelError(
                "Missing required runtime services: " + ", ".join(sorted(missing))
            )
