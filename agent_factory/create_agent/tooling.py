from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import BaseTool

from agent_factory.create_agent.authoring_tool import (
    CREATE_AGENT_AUTHORING_TOOL_ID,
    build_create_agent_authoring_tool_spec,
)
from agent_factory.create_agent.capability_inventory import build_capability_inventory
from agent_factory.create_agent.control_tool import (
    CREATE_AGENT_CONTROL_TOOL_ID,
    CREATE_AGENT_WORKSPACE_RESOURCE,
    build_create_agent_control_tool_spec,
)
from agent_factory.create_agent.models import (
    ACTION_FILE,
    PUBLISH_FILE,
    PUBLISH_DECISION_FILE,
    SKILL_GATEWAY_STATE_FILE,
    SYSTEM_STATE_FILE,
    TASK_ANALYSIS_FILE,
    TOOL_PROBE_FILE,
    VALIDATION_FILE,
    VALIDATION_STATE_FILE,
)
from agent_factory.create_agent.publish_tool import (
    CREATE_AGENT_PACKAGE_REGISTRY_RESOURCE,
    CREATE_AGENT_PUBLISH_TOOL_ID,
    build_create_agent_publish_tool_spec,
)
from agent_factory.create_agent.probe_tool import CREATE_AGENT_PROBE_TOOL_ID, build_create_agent_probe_tool_spec
from agent_factory.create_agent.stage_context import CREATE_AGENT_STAGE_CONTEXT_RESOURCE, stage_context_payload
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.create_agent.stage_tool import CREATE_AGENT_STAGE_TOOL_ID, build_create_agent_stage_tool_spec
from agent_factory.create_agent.validate_tool import CREATE_AGENT_VALIDATE_TOOL_ID, build_create_agent_validate_tool_spec
from agent_factory.tooling.builtins.resource_set.resource_set import RESOURCE_SET_STORE_KEY, ResourceSetStore
from agent_factory.tooling.builtins.tool_output.specs import get_tool_output_tool_specs
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.factory_extensions import FactoryExtensionLoadReport, FactoryExtensionManager, default_factory_extension_root
from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE, ToolOutputStore
from agent_factory.tooling.providers import BuiltinToolProvider, ToolProviderContext, ToolProviderResult
from agent_factory.tooling.registry import ToolRegistry
from agent_factory.paths import factory_artifact_path
from agent_factory.runtime_attachments import ATTACHMENT_INPUT_DIR
from agent_factory.tooling.skills import (
    SKILL_TOOL_ID,
    SkillRegistry,
    build_skill_tool_spec,
    parse_skill_directory,
)
from agent_factory.tooling.skills.schema import SkillGatewayState
from agent_factory.tooling.skills.skill_tool import SKILL_GATEWAY_STATE_RESOURCE_KEY


CREATE_AGENT_BUILTIN_TOOL_IDS = {
    "read",
    "write",
    "edit",
    "multi_edit",
    "glob",
    "grep",
    "ls",
    "tool_output",
    "resource_set",
}
CREATE_AGENT_ASSIST_TOOL_IDS = {
    "read",
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
    capability_inventory: dict[str, Any]


class CreateAgentToolEnvironmentBuilder:
    def __init__(self, *, extension_manager: FactoryExtensionManager | None = None) -> None:
        self.extension_manager = extension_manager or FactoryExtensionManager()

    def build(
        self,
        *,
        workspace_root: str | Path,
        mode: Literal["manufacture", "assist", "evolution"] = "manufacture",
    ) -> CreateAgentToolEnvironment:
        workspace = Path(workspace_root).expanduser().resolve()
        create_agent_workspace = CreateAgentWorkspace(workspace)
        extension_root = default_factory_extension_root()
        context = ToolProviderContext(
            package_root=workspace,
            extension_root=extension_root,
            resources={
                "builtin_workspace_root": str(workspace),
                "builtin_allow_external_paths": False,
            },
        )
        authoring_mode = mode in {"manufacture", "evolution"}
        builtin_tool_ids = CREATE_AGENT_BUILTIN_TOOL_IDS if authoring_mode else CREATE_AGENT_ASSIST_TOOL_IDS
        builtin_result = BuiltinToolProvider(tool_ids=builtin_tool_ids).discover(context)
        if authoring_mode:
            extension_result, extension_report = self.extension_manager.discover(context=context)
        else:
            extension_result = ToolProviderResult()
            extension_report = FactoryExtensionLoadReport(extension_root=str(extension_root))
        provider_result = builtin_result.merge(extension_result) if authoring_mode else builtin_result
        runtime_resources = {
            **builtin_result.runtime_resources,
            **(extension_result.runtime_resources if authoring_mode else {}),
            CREATE_AGENT_WORKSPACE_RESOURCE: {"root": str(workspace)},
            CREATE_AGENT_STAGE_CONTEXT_RESOURCE: stage_context_payload(workspace),
            TOOL_OUTPUT_STORE_RESOURCE: ToolOutputStore(workspace / ".factory" / "tool_outputs"),
        }
        if authoring_mode:
            runtime_resources[RESOURCE_SET_STORE_KEY] = ResourceSetStore()
            runtime_resources[CREATE_AGENT_PACKAGE_REGISTRY_RESOURCE] = str(factory_artifact_path("packages"))
        filesystem_resource = runtime_resources.get("filesystem")
        if isinstance(filesystem_resource, dict) and authoring_mode:
            filesystem_resource[CREATE_AGENT_STAGE_CONTEXT_RESOURCE] = runtime_resources[CREATE_AGENT_STAGE_CONTEXT_RESOURCE]
            read_only_paths = filesystem_resource.setdefault("read_only_paths", [])
            if isinstance(read_only_paths, list):
                read_only_paths.append(f".factory/{ATTACHMENT_INPUT_DIR}")
            filesystem_resource["protected_write_paths"] = [
                ACTION_FILE,
                SYSTEM_STATE_FILE,
                VALIDATION_FILE,
                VALIDATION_STATE_FILE,
                TOOL_PROBE_FILE,
                PUBLISH_FILE,
                PUBLISH_DECISION_FILE,
                SKILL_GATEWAY_STATE_FILE,
                TASK_ANALYSIS_FILE,
                ".factory/manufacturing_trace.json",
                ".factory/tool_outputs",
                ".agent_runtime",
            ]
            filesystem_resource["managed_paths"] = {
                ACTION_FILE: {
                    "read_tool": CREATE_AGENT_CONTROL_TOOL_ID,
                    "write_tool": CREATE_AGENT_CONTROL_TOOL_ID,
                },
                SYSTEM_STATE_FILE: {
                    "read_tool": CREATE_AGENT_STAGE_TOOL_ID,
                    "write_tool": CREATE_AGENT_STAGE_TOOL_ID,
                },
                TASK_ANALYSIS_FILE: {
                    "read_tool": CREATE_AGENT_STAGE_TOOL_ID,
                    "write_tool": "create-agent task analysis",
                },
            }
            filesystem_resource["managed_write_paths"] = {
                "agent_package.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "assembly_spec.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "render_manifest.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "resources.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/tools.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/dependencies.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/resources.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/scheduler_seed.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/artifact.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/context.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/knowledge.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/model.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/sandbox.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/scheduler.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/session.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/state.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/memory.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/render.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "contracts/trace.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "extensions/mcp_servers.json": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "tools": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "knowledge": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
                "state": {"write_tool": CREATE_AGENT_AUTHORING_TOOL_ID},
            }
        if authoring_mode:
            skill_registry = _create_agent_skill_registry(
                runtime_resources.get("skills"),
                gateway_state=_load_skill_gateway_state(create_agent_workspace.skill_gateway_state_path),
            )
            if skill_registry.list_metadata():
                runtime_resources["skills"] = skill_registry.to_resource_payload()
                runtime_resources[SKILL_GATEWAY_STATE_RESOURCE_KEY] = str(create_agent_workspace.skill_gateway_state_path)
                provider_result.system_tool_ids = sorted(set([*provider_result.system_tool_ids, SKILL_TOOL_ID]))
                skill_specs = [
                    build_skill_tool_spec(
                        skill_registry,
                        persist_gateway_state=True,
                        stage_context_resource=CREATE_AGENT_STAGE_CONTEXT_RESOURCE,
                    )
                ]
            else:
                skill_specs = []
            provider_result.system_tool_ids = sorted(
                set(
                    [
                        *provider_result.system_tool_ids,
                        CREATE_AGENT_AUTHORING_TOOL_ID,
                        CREATE_AGENT_CONTROL_TOOL_ID,
                        CREATE_AGENT_STAGE_TOOL_ID,
                        CREATE_AGENT_PROBE_TOOL_ID,
                        CREATE_AGENT_VALIDATE_TOOL_ID,
                        *([CREATE_AGENT_PUBLISH_TOOL_ID] if mode == "manufacture" else []),
                    ]
                )
            )
            extra_specs = [
                build_create_agent_control_tool_spec(),
                build_create_agent_authoring_tool_spec(),
                build_create_agent_stage_tool_spec(),
                build_create_agent_probe_tool_spec(),
                build_create_agent_validate_tool_spec(),
                *([build_create_agent_publish_tool_spec()] if mode == "manufacture" else []),
                *skill_specs,
            ]
        else:
            extra_specs = []
        specs = _stable_specs(
            _unique_specs(
                provider_result,
                extra_specs=extra_specs,
            )
        )
        extension_specs = _stable_specs(extension_result.tool_specs) if authoring_mode else []
        capability_inventory = build_capability_inventory(
            manufacturing_specs=specs,
            extension_specs=extension_specs,
        )
        registry = ToolRegistry(specs)
        compiler = ToolCompiler(
            package_root=workspace,
            resources=runtime_resources,
            allowed_python_roots=[extension_root],
            mcp_clients=self.extension_manager.mcp_tool_clients() if authoring_mode else {},
        )
        tools = _stable_tools(compiler.compile_many(registry.all()))
        return CreateAgentToolEnvironment(
            tools=tools,
            tool_ids=[tool.name for tool in tools],
            system_tool_ids=sorted(set(provider_result.system_tool_ids)),
            extension_report=extension_report.model_dump(mode="json"),
            capability_inventory=capability_inventory.model_dump(mode="json"),
        )


def _stable_specs(specs: list[Any]) -> list[Any]:
    return sorted(specs, key=lambda spec: str(spec.id))


def _stable_tools(tools: list[BaseTool]) -> list[BaseTool]:
    return sorted(tools, key=lambda tool: str(tool.name))


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


def _create_agent_skill_registry(existing_payload: Any, *, gateway_state: SkillGatewayState | None = None) -> SkillRegistry:
    registry = (
        SkillRegistry.from_resource_payload(existing_payload)
        if isinstance(existing_payload, dict)
        else SkillRegistry()
    )
    if gateway_state is not None:
        registry.gateway_state = gateway_state
    if not CREATE_AGENT_SKILLS_ROOT.is_dir():
        return registry
    for child in sorted(item for item in CREATE_AGENT_SKILLS_ROOT.iterdir() if item.is_dir()):
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            continue
        registry.register(parse_skill_directory(child))
    return registry


def _load_skill_gateway_state(path: Path) -> SkillGatewayState | None:
    if not path.exists():
        return None
    try:
        return SkillGatewayState.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        # Invalid skill gateway state is non-fatal during tool environment setup.
        # The validator will detect and report the broken JSON so the LLM can repair it.
        return None
