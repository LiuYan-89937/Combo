from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from agent_factory.runtime_kernel.types import ToolExecutionResult


class ToolRegistryAdapter(Protocol):
    def list_tool_ids(self) -> list[str]:
        ...

    def execute(self, tool_id: str, arguments: dict[str, Any], *, state: Any) -> ToolExecutionResult:
        ...


class InMemoryToolRegistry:
    def __init__(
        self,
        tools: dict[str, Callable[[dict[str, Any], Any], ToolExecutionResult | dict[str, Any]]] | None = None,
    ) -> None:
        self._tools = dict(tools or {})

    def list_tool_ids(self) -> list[str]:
        return sorted(self._tools)

    def execute(self, tool_id: str, arguments: dict[str, Any], *, state: Any) -> ToolExecutionResult:
        if tool_id not in self._tools:
            return ToolExecutionResult(
                status="failed",
                error=f"Unknown tool: {tool_id}",
                observation_summary=f"Unknown tool: {tool_id}",
            )
        result = self._tools[tool_id](arguments, state)
        if isinstance(result, ToolExecutionResult):
            return result
        if not isinstance(result, dict):
            return ToolExecutionResult(
                status="failed",
                error="Tool output must be a mapping.",
                observation_summary="Tool output must be a mapping.",
            )
        status = str(result.get("status") or "completed")
        if status not in {"completed", "failed", "interrupted"}:
            status = "completed"
        return ToolExecutionResult(
            status=status,  # type: ignore[arg-type]
            output=result,
            error=result.get("error"),
            interrupt_type=result.get("interrupt_type"),
            observation_summary=result.get("observation_summary"),
        )
