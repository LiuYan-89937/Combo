from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from agent_factory.create_agent.control_tool import (
    CREATE_AGENT_CONTROL_TOOL_ID,
    CREATE_AGENT_WORKSPACE_RESOURCE,
    build_create_agent_control_tool_spec,
)
from agent_factory.create_agent.models import ACTION_FILE, TODO_FILE
from agent_factory.create_agent.todo_tool import CREATE_AGENT_TODO_TOOL_ID, build_create_agent_todo_tool_spec
from agent_factory.create_agent.validate_tool import CREATE_AGENT_VALIDATE_TOOL_ID, build_create_agent_validate_tool_spec
from agent_factory.tooling.builtins.tool_output.specs import get_tool_output_tool_specs
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.factory_extensions import FactoryExtensionManager, default_factory_extension_root
from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE, ToolOutputStore
from agent_factory.tooling.providers import BuiltinToolProvider, ToolProviderContext, ToolProviderResult
from agent_factory.tooling.registry import ToolRegistry
from agent_factory.tooling.skills import (
    SKILL_TOOL_ID,
    SkillRegistry,
    build_skill_tool_spec,
    parse_skill_directory,
)


CREATE_AGENT_BUILTIN_TOOL_IDS = {
    "read",
    "write",
    "edit",
    "multi_edit",
    "glob",
    "grep",
    "ls",
    "tool_output",
}

CREATE_AGENT_SKILLS_ROOT = Path(__file__).resolve().parent / "skills"


@dataclass(frozen=True, slots=True)
class CreateAgentToolEnvironment:
    tools: list[BaseTool]
    tool_ids: list[str]
    system_tool_ids: list[str]
    extension_report: dict[str, Any]


class CreateAgentToolEnvironmentBuilder:
    def __init__(self, *, extension_manager: FactoryExtensionManager | None = None) -> None:
        self.extension_manager = extension_manager or FactoryExtensionManager()

    def build(self, *, workspace_root: str | Path) -> CreateAgentToolEnvironment:
        workspace = Path(workspace_root).expanduser().resolve()
        extension_root = default_factory_extension_root()
        context = ToolProviderContext(
            package_root=workspace,
            extension_root=extension_root,
            resources={
                "builtin_workspace_root": str(workspace),
                "builtin_allow_external_paths": False,
            },
        )
        builtin_result = BuiltinToolProvider(tool_ids=CREATE_AGENT_BUILTIN_TOOL_IDS).discover(context)
        extension_result, extension_report = self.extension_manager.discover(context=context)
        provider_result = builtin_result.merge(extension_result)
        runtime_resources = {
            **builtin_result.runtime_resources,
            **extension_result.runtime_resources,
            CREATE_AGENT_WORKSPACE_RESOURCE: {"root": str(workspace)},
            TOOL_OUTPUT_STORE_RESOURCE: ToolOutputStore(workspace / ".factory" / "tool_outputs"),
        }
        filesystem_resource = runtime_resources.get("filesystem")
        if isinstance(filesystem_resource, dict):
            filesystem_resource["protected_write_paths"] = [ACTION_FILE, TODO_FILE]
        skill_registry = _create_agent_skill_registry(runtime_resources.get("skills"))
        if skill_registry.list_metadata():
            runtime_resources["skills"] = skill_registry.to_resource_payload()
            provider_result.system_tool_ids = sorted(set([*provider_result.system_tool_ids, SKILL_TOOL_ID]))
            skill_specs = [build_skill_tool_spec(skill_registry)]
        else:
            skill_specs = []
        provider_result.system_tool_ids = sorted(
            set(
                [
                    *provider_result.system_tool_ids,
                    CREATE_AGENT_CONTROL_TOOL_ID,
                    CREATE_AGENT_TODO_TOOL_ID,
                    CREATE_AGENT_VALIDATE_TOOL_ID,
                ]
            )
        )
        specs = _unique_specs(
            provider_result,
            extra_specs=[
                build_create_agent_control_tool_spec(),
                build_create_agent_todo_tool_spec(),
                build_create_agent_validate_tool_spec(),
                *skill_specs,
            ],
        )
        registry = ToolRegistry(specs)
        compiler = ToolCompiler(
            package_root=workspace,
            resources=runtime_resources,
            allowed_python_roots=[extension_root],
            mcp_clients=self.extension_manager.mcp_tool_clients(),
        )
        tools = compiler.compile_many(registry.all())
        return CreateAgentToolEnvironment(
            tools=tools,
            tool_ids=[tool.name for tool in tools],
            system_tool_ids=sorted(set(provider_result.system_tool_ids)),
            extension_report=extension_report.model_dump(mode="json"),
        )


def _unique_specs(result: ToolProviderResult, *, extra_specs=()):
    specs = []
    seen = set()
    for spec in [
        *(spec for spec in result.tool_specs if spec.id != SKILL_TOOL_ID),
        *get_tool_output_tool_specs(),
        *extra_specs,
    ]:
        if spec.id in seen:
            continue
        seen.add(spec.id)
        specs.append(spec)
    return specs


def _create_agent_skill_registry(existing_payload: Any) -> SkillRegistry:
    registry = (
        SkillRegistry.from_resource_payload(existing_payload)
        if isinstance(existing_payload, dict)
        else SkillRegistry()
    )
    if not CREATE_AGENT_SKILLS_ROOT.is_dir():
        return registry
    for child in sorted(item for item in CREATE_AGENT_SKILLS_ROOT.iterdir() if item.is_dir()):
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        registry.register(parse_skill_directory(child))
    return registry
