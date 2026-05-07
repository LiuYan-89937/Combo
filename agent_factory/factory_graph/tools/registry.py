from __future__ import annotations

from langchain_core.tools import BaseTool

from agent_factory.factory_graph.tools.filesystem import FILE_TOOLS
from agent_factory.factory_graph.tools.search import SEARCH_TOOLS
from agent_factory.factory_graph.tools.shell import SHELL_TOOLS


def get_factory_base_tools() -> list[BaseTool]:
    """Return the standard tools assigned to the Factory graph."""

    return [*FILE_TOOLS, *SEARCH_TOOLS, *SHELL_TOOLS]


def get_factory_graph_tools() -> list[BaseTool]:
    """Return executable tools accepted by ToolNode."""

    return get_factory_base_tools()


def get_factory_model_tools() -> list[BaseTool]:
    """Return tools exposed to chat models."""

    return get_factory_base_tools()


def get_factory_base_tool_ids() -> list[str]:
    return [tool.name for tool in get_factory_base_tools()]
