from __future__ import annotations

from agent_factory.tooling.builtins.filesystem.specs import get_filesystem_tool_specs
from agent_factory.tooling.builtins.network.specs import get_network_tool_specs
from agent_factory.tooling.builtins.process.specs import get_process_tool_specs
from agent_factory.tooling.spec import ToolSpec


def get_builtin_tool_specs() -> list[ToolSpec]:
    return [
        *get_filesystem_tool_specs(),
        *get_process_tool_specs(),
        *get_network_tool_specs(),
    ]


def get_builtin_tool_ids() -> list[str]:
    return [tool.id for tool in get_builtin_tool_specs()]


def get_builtin_protected_tool_ids() -> list[str]:
    return [tool.id for tool in get_builtin_tool_specs() if tool.approval_required]
