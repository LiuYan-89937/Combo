from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from agent_factory.runtime_kernel.errors import RuntimeKernelError


class RuntimeServices(BaseModel):
    """Application-owned dependencies shared by the two fixed runtime graphs."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    model_operation_service: object
    tool_registry: object
    graph_store: object
    context_system: object
    context_engine: object
    observability_manager: object
    checkpointer: object
    scheduler_store: object | None = None
    scheduler_runtime: object | None = None
    artifact_store: object | None = None
    runtime_context_resources: object

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
