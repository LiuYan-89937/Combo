from __future__ import annotations

from collections.abc import Iterable

from langchain_core.tools import BaseTool

from agent_factory.tooling.spec import ModelToolView, ToolSpec, model_tool_view


class ToolRegistry:
    def __init__(self, tools: Iterable[ToolSpec] | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: ToolSpec) -> None:
        if tool.id in self._tools:
            raise ValueError(f"duplicate tool id: {tool.id}")
        self._tools[tool.id] = tool

    def get(self, tool_id: str) -> ToolSpec:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise KeyError(f"unknown tool id: {tool_id}") from exc

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def ids(self) -> list[str]:
        return list(self._tools.keys())

    def model_views(self) -> list[ModelToolView]:
        return [model_tool_view(tool) for tool in self._tools.values()]


def get_factory_tools() -> list[BaseTool]:
    """Return currently registered Factory tools.

    The old ``factory_graph.tools`` implementation has been cleared. New tools
    must be registered through the unified ToolSpec-based system.
    """

    return []


def get_factory_model_tools() -> list[BaseTool]:
    return get_factory_tools()


def get_factory_base_tool_ids() -> list[str]:
    return [tool.name for tool in get_factory_tools()]


def get_factory_protected_tool_ids() -> list[str]:
    return []
