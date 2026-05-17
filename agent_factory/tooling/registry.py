from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from langchain_core.tools import BaseTool

from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.builtins import (
    get_builtin_protected_tool_ids,
    get_builtin_tool_ids,
    get_builtin_tool_specs,
)
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
    compiler = ToolCompiler(
        resources={
            "filesystem": {
                "root": str(_default_filesystem_root()),
                "allow_external": False,
            }
        }
    )
    return compiler.compile_many(get_builtin_tool_specs())


def get_factory_tool_specs() -> list[ToolSpec]:
    return get_builtin_tool_specs()


def get_factory_model_tools() -> list[BaseTool]:
    return get_factory_tools()


def get_factory_base_tool_ids() -> list[str]:
    return get_builtin_tool_ids()


def get_factory_protected_tool_ids() -> list[str]:
    return get_builtin_protected_tool_ids()


def _default_filesystem_root() -> Path:
    current = Path(os.getcwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "agent_factory").is_dir():
            return candidate
    return current
