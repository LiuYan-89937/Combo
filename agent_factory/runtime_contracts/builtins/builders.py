from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.errors import GraphInterrupt

from agent_factory.memory_system import default_agent_runtime
from agent_factory.memory_system.background import MemoryBackgroundWorker
from agent_factory.memory_system.store_index import build_memory_store_index
from agent_factory.runtime_contracts.builder import RuntimeBuildContext
from agent_factory.runtime_contracts.contribution import RuntimeContribution, RuntimeDiagnostic
from agent_factory.runtime_contracts.schema import (
    MemoryContract,
    DependenciesContract,
    ModelContract,
    RenderContract,
    ResourcesContract,
    SandboxRuntimeContract,
    SchedulerContract,
    SessionContract,
    ToolsContract,
)
from agent_factory.scheduler_system import SchedulerExecutor, SchedulerRuntime, SchedulerWorker, SQLiteSchedulerStore
from agent_factory.runtime_kernel.adapters import InMemoryToolRegistry, LangChainModelServiceAdapter
from agent_factory.runtime_kernel.wrappers.system_memory import MEMORY_RETRIEVE_SYSTEM_WRAPPER_ID
from agent_factory.runtime_kernel.wrappers.system_render import RENDER_NODE_SYSTEM_WRAPPER_ID
from agent_factory.runtime_kernel.persistence import (
    LangGraphCheckpointerConfig,
    LangGraphCheckpointerFactory,
    LangGraphStoreConfig,
    LangGraphStoreFactory,
)
from agent_factory.runtime_kernel.types import ToolExecutionResult
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.providers import BuiltinToolProvider, PackageToolProvider, ToolProviderContext
from agent_factory.tooling.registry import ToolRegistry
from agent_factory.runtime_kernel.extensions.manager import AgentInstanceExtensionManager


class SessionContractBuilder:
    contract_type = "session"
    contract_version = "session_contract.v0"

    def build(self, contract: SessionContract, context: RuntimeBuildContext) -> RuntimeContribution:
        config = contract.config
        checkpoint_path = Path(config.checkpoint_path) if config.checkpointer_backend == "sqlite" else None
        checkpointer = LangGraphCheckpointerFactory().build(
            LangGraphCheckpointerConfig(
                backend=config.checkpointer_backend,
                path=checkpoint_path,
            )
        ).saver
        return RuntimeContribution(
            services={"checkpointer": checkpointer},
            session_config={
                "session_root": config.session_root,
                "checkpointer_backend": config.checkpointer_backend,
                "checkpoint_path": config.checkpoint_path,
            },
        )


class ToolsContractBuilder:
    contract_type = "tools"
    contract_version = "tools_contract.v0"

    def build(self, contract: ToolsContract, context: RuntimeBuildContext) -> RuntimeContribution:
        config = contract.config
        specs = []
        diagnostics: list[RuntimeDiagnostic] = []
        runtime_resources: dict[str, Any] = {}
        mcp_clients = {}
        system_tool_ids: set[str] = set()
        instance_extension_root = Path(config.instance_extension_root).expanduser().resolve()
        provider_context = ToolProviderContext(
            package_root=context.package_root,
            extension_root=instance_extension_root,
            resources=context.resources,
        )
        if config.builtin_tools_enabled:
            builtin_result = BuiltinToolProvider(tool_ids=config.builtin_tool_ids).discover(
                ToolProviderContext(
                    package_root=context.package_root,
                    extension_root=instance_extension_root,
                    resources={
                        "builtin_workspace_root": config.builtin_workspace_root,
                        "builtin_allow_external_paths": config.builtin_allow_external_paths,
                    },
                )
            )
            if "scheduler_runtime" not in context.resources:
                builtin_result.tool_specs = [spec for spec in builtin_result.tool_specs if spec.id != "scheduler"]
                builtin_result.system_tool_ids = [tool_id for tool_id in builtin_result.system_tool_ids if tool_id != "scheduler"]
            specs.extend(builtin_result.tool_specs)
            system_tool_ids.update(builtin_result.system_tool_ids)
            runtime_resources.update(builtin_result.runtime_resources)
            diagnostics.extend(_provider_diagnostics(builtin_result.diagnostics))
        if config.package_tools_enabled:
            package_result = PackageToolProvider().discover(provider_context)
            specs.extend(package_result.tool_specs)
            system_tool_ids.update(package_result.system_tool_ids)
            runtime_resources.update(package_result.runtime_resources)
            diagnostics.extend(_provider_diagnostics(package_result.diagnostics))
        if config.instance_extensions_enabled:
            manager = AgentInstanceExtensionManager(extension_root=instance_extension_root)
            extension_result, extension_report = manager.discover(context=provider_context)
            specs.extend(extension_result.tool_specs)
            system_tool_ids.update(extension_result.system_tool_ids)
            runtime_resources.update(extension_result.runtime_resources)
            mcp_clients = manager.mcp_tool_clients()
            diagnostics.extend(_provider_diagnostics(extension_result.diagnostics))
            diagnostics.append(
                RuntimeDiagnostic(
                    where="tools.extensions",
                    level="info",
                    message="agent extension discovery completed",
                    details=extension_report.model_dump(mode="json"),
                )
            )
        registry = ToolRegistry(specs)
        compiler = ToolCompiler(
            package_root=context.package_root,
            resources={**context.resources, **runtime_resources},
            allowed_python_roots=[instance_extension_root],
            mcp_clients=mcp_clients,
        )
        compiled_tools = {tool.name: tool for tool in compiler.compile_many(registry.all())}
        runtime_registry = InMemoryToolRegistry(
            {
                tool_id: _runtime_tool_executor(tool_id, tool)
                for tool_id, tool in compiled_tools.items()
            },
            model_tools=compiled_tools,
            system_tool_ids=system_tool_ids,
        )
        return RuntimeContribution(services={"tool_registry": runtime_registry}, diagnostics=diagnostics)


class MemoryContractBuilder:
    contract_type = "memory"
    contract_version = "memory_contract.v0"

    def build(self, contract: MemoryContract, context: RuntimeBuildContext) -> RuntimeContribution:
        config = contract.config.memory_system
        if not config.enabled:
            return RuntimeContribution(
                services={
                    "memory_store": None,
                    "memory_system": default_agent_runtime(
                        agent_id=context.package.assembly_spec.agent.id,
                        config=config,
                        store=None,
                    ),
                }
            )
        store_config = LangGraphStoreConfig(
            backend=config.store.backend,
            path=Path(config.store.path) if config.store.backend == "sqlite" else None,
            index=build_memory_store_index(config),
        )
        store = LangGraphStoreFactory().build(store_config).store
        runtime = default_agent_runtime(
            agent_id=context.package.assembly_spec.agent.id,
            config=config,
            store=store,
        )
        diagnostics: list[RuntimeDiagnostic] = []
        background_workers: list[Any] = []
        if config.write_enabled:
            try:
                worker = MemoryBackgroundWorker(store=store, config=config)
                worker.start()
                runtime.writer = worker
                background_workers.append(worker)
            except Exception as exc:
                runtime.writer = None
                diagnostics.append(
                    RuntimeDiagnostic(
                        where="memory.background_worker",
                        level="warning",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                )
        return RuntimeContribution(
            services={"memory_store": store, "memory_system": runtime},
            system_wrappers=[MEMORY_RETRIEVE_SYSTEM_WRAPPER_ID],
            background_workers=background_workers,
            diagnostics=diagnostics,
        )


class ModelContractBuilder:
    contract_type = "model"
    contract_version = "model_contract.v0"

    def build(self, contract: ModelContract, context: RuntimeBuildContext) -> RuntimeContribution:
        if contract.config.source != "factory_runtime_env":
            raise ValueError(f"unsupported model contract source: {contract.config.source}")
        if contract.config.role != "main":
            raise ValueError(f"unsupported model contract role: {contract.config.role}")
        return RuntimeContribution(services={"model_service": LangChainModelServiceAdapter()})


class RenderContractBuilder:
    contract_type = "render"
    contract_version = "render_contract.v0"

    def build(self, contract: RenderContract, context: RuntimeBuildContext) -> RuntimeContribution:
        return RuntimeContribution(
            render_manifest=context.package.render_manifest,
            system_wrappers=[RENDER_NODE_SYSTEM_WRAPPER_ID],
        )


class ResourcesContractBuilder:
    contract_type = "resources"
    contract_version = "resources_contract.v0"

    def build(self, contract: ResourcesContract, context: RuntimeBuildContext) -> RuntimeContribution:
        return RuntimeContribution(resources=context.resources)


class SandboxContractBuilder:
    contract_type = "sandbox"
    contract_version = "sandbox_contract.v0"

    def build(self, contract: SandboxRuntimeContract, context: RuntimeBuildContext) -> RuntimeContribution:
        return RuntimeContribution(sandbox_contract=context.sandbox_contract)


class SchedulerContractBuilder:
    contract_type = "scheduler"
    contract_version = "scheduler_contract.v0"

    def build(self, contract: SchedulerContract, context: RuntimeBuildContext) -> RuntimeContribution:
        config = contract.config
        owner_id = context.package.assembly_spec.agent.id
        store = SQLiteSchedulerStore(config.store_path)
        runtime = SchedulerRuntime(
            config=config,
            owner_type="agent",
            owner_id=owner_id,
            store=store,
            executor=SchedulerExecutor(),
        )
        worker = SchedulerWorker(runtime)
        return RuntimeContribution(
            services={"scheduler_store": store, "scheduler_runtime": runtime},
            resources={"scheduler_runtime": runtime},
            background_workers=[worker],
            diagnostics=[
                RuntimeDiagnostic(
                    where="scheduler.runtime",
                    level="info",
                    message="scheduler runtime configured",
                    details={"store_path": config.store_path, "owner_id": owner_id},
                )
            ],
        )


class DependenciesContractBuilder:
    contract_type = "dependencies"
    contract_version = "dependencies_contract.v0"

    def build(self, contract: DependenciesContract, context: RuntimeBuildContext) -> RuntimeContribution:
        return RuntimeContribution(dependency_plan=contract.config.model_dump(mode="json"))


def _runtime_tool_executor(tool_id: str, tool) -> Any:
    def execute(arguments: dict[str, Any], _state: Any) -> ToolExecutionResult:
        try:
            output = tool.invoke(arguments)
        except GraphInterrupt:
            raise
        except Exception as exc:
            return ToolExecutionResult(
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
                observation_summary=f"{tool_id} failed: {type(exc).__name__}",
            )
        if isinstance(output, dict):
            if output.get("type") == "tool_observation":
                return _tool_observation_result(output)
            status = str(output.get("status") or "completed")
            if status not in {"completed", "failed", "interrupted"}:
                status = "completed"
            return ToolExecutionResult(
                status=status,  # type: ignore[arg-type]
                output=output,
                error=output.get("error"),
                interrupt_type=output.get("interrupt_type"),
                observation_summary=output.get("observation_summary"),
            )
        return ToolExecutionResult(status="completed", output={"value": output})

    return execute


def _tool_observation_result(observation: dict[str, Any]) -> ToolExecutionResult:
    observation_status = str(observation.get("status") or "")
    message = str(observation.get("message") or observation_status or "tool observation")
    if observation_status == "completed":
        return ToolExecutionResult(
            status="completed",
            output=observation,
            observation_summary=message,
            metadata={"tool_observation_status": observation_status},
        )
    return ToolExecutionResult(
        status="failed",
        output=observation,
        error=message,
        observation_summary=message,
        metadata={"tool_observation_status": observation_status},
    )


def _provider_diagnostics(items) -> list[RuntimeDiagnostic]:
    return [
        RuntimeDiagnostic(
            where=f"tools.provider.{item.provider_id}",
            level=item.level,
            message=item.message,
            details=item.details,
        )
        for item in items
    ]
