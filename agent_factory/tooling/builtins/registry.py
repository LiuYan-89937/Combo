from __future__ import annotations

from agent_factory.tooling.builtins.background_tasks.specs import get_background_tasks_tool_specs
from agent_factory.tooling.builtins.browser.specs import get_browser_tool_specs
from agent_factory.tooling.builtins.filesystem.specs import get_filesystem_tool_specs
from agent_factory.tooling.builtins.knowledge.specs import get_knowledge_tool_specs
from agent_factory.tooling.builtins.network.specs import get_network_tool_specs
from agent_factory.tooling.builtins.process.specs import get_process_tool_specs
from agent_factory.tooling.builtins.resource_set.specs import get_resource_set_tool_specs
from agent_factory.tooling.builtins.scheduler.specs import get_scheduler_tool_specs
from agent_factory.tooling.builtins.skillhub.specs import get_skillhub_tool_specs
from agent_factory.tooling.builtins.tool_output.specs import get_tool_output_tool_specs
from agent_factory.tooling.spec import ToolSpec

IMPLEMENTED_BUILTIN_TOOL_IDS = {
    "read",
    "write",
    "edit",
    "glob",
    "grep",
    "ls",
    "shell",
    "shell_status",
    "shell_stop",
    "scheduler",
    "knowledge",
    "skillhub",
    "tool_output",
    "resource_set",
    "background_tasks",
    "browser_open",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_select",
    "browser_press",
    "browser_scroll",
    "browser_wait",
    "browser_extract",
    "browser_screenshot",
    "browser_download",
    "browser_upload",
    "browser_tabs",
    "browser_close",
}

ALWAYS_AVAILABLE_SYSTEM_TOOL_IDS = {"tool_output"}
READ_ONLY_SYSTEM_TOOL_IDS = {
    "read",
    "glob",
    "grep",
    "ls",
    "shell_status",
    "knowledge",
    "scheduler",
    "skillhub",
    "tool_output",
    "resource_set",
    "background_tasks",
    "browser_snapshot",
    "browser_extract",
    "browser_screenshot",
    "browser_tabs",
}


def get_builtin_tool_specs() -> list[ToolSpec]:
    catalog = [
        *get_filesystem_tool_specs(),
        *get_process_tool_specs(),
        *get_network_tool_specs(),
        *get_scheduler_tool_specs(),
        *get_knowledge_tool_specs(),
        *get_skillhub_tool_specs(),
        *get_tool_output_tool_specs(),
        *get_resource_set_tool_specs(),
        *get_background_tasks_tool_specs(),
        *get_browser_tool_specs(),
    ]
    return [tool for tool in catalog if tool.id in IMPLEMENTED_BUILTIN_TOOL_IDS]


def get_builtin_tool_ids() -> list[str]:
    return [tool.id for tool in get_builtin_tool_specs()]


def get_builtin_protected_tool_ids() -> list[str]:
    return [tool.id for tool in get_builtin_tool_specs() if tool.risk_level in {"medium", "high"}]


def get_always_available_system_tool_ids() -> set[str]:
    return set(ALWAYS_AVAILABLE_SYSTEM_TOOL_IDS)


def get_contextual_system_tool_ids() -> set[str]:
    return set()


def get_read_only_system_tool_ids() -> set[str]:
    return set(READ_ONLY_SYSTEM_TOOL_IDS)
