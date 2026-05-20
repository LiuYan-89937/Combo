from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from agent_factory.runtime_kernel.errors import RuntimeKernelError


class RuntimeServices(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    model_service: object | None = None
    tool_registry: object | None = None
    memory_store: object | None = None
    memory_system: object | None = None
    knowledge_engine: object | None = None
    context_engine: object | None = None
    policy_engine: object | None = None
    observability_manager: object | None = None
    checkpointer: object | None = None
    harness_bridge: object | None = None
    scheduler_store: object | None = None
    scheduler_runtime: object | None = None

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
