from __future__ import annotations

from agent_factory.tooling.builtins.filesystem.specs import get_filesystem_tool_specs
from agent_factory.tooling.builtins.knowledge.specs import get_knowledge_tool_specs
from agent_factory.tooling.builtins.network.specs import get_network_tool_specs
from agent_factory.tooling.builtins.process.specs import get_process_tool_specs
from agent_factory.tooling.builtins.scheduler.specs import get_scheduler_tool_specs
from agent_factory.tooling.builtins.tool_output.specs import get_tool_output_tool_specs
from agent_factory.tooling.spec import ToolSpec


IMPLEMENTED_BUILTIN_TOOL_IDS = {
    "read",
    "write",
    "edit",
    "multi_edit",
    "glob",
    "grep",
    "ls",
    "bash",
    "bash_status",
    "bash_stop",
    "scheduler",
    "knowledge",
    "tool_output",
}

ALWAYS_AVAILABLE_SYSTEM_TOOL_IDS = {"tool_output"}


def get_builtin_tool_specs() -> list[ToolSpec]:
    catalog = [
        *get_filesystem_tool_specs(),
        *get_process_tool_specs(),
        *get_network_tool_specs(),
        *get_scheduler_tool_specs(),
        *get_knowledge_tool_specs(),
        *get_tool_output_tool_specs(),
    ]
    return [tool for tool in catalog if tool.id in IMPLEMENTED_BUILTIN_TOOL_IDS]


def get_builtin_tool_ids() -> list[str]:
    return [tool.id for tool in get_builtin_tool_specs()]


def get_builtin_protected_tool_ids() -> list[str]:
    return [tool.id for tool in get_builtin_tool_specs() if tool.risk_level in {"medium", "high"}]


def get_always_available_system_tool_ids() -> set[str]:
    return set(ALWAYS_AVAILABLE_SYSTEM_TOOL_IDS)
