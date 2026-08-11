from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import platform
import sys

from agent_factory import __version__
from agent_factory.context_system.runtime import default_context_runtime
from agent_factory.dynamic_runtime import (
    CapabilityResolutionConfig,
    CapabilitySearchConfig,
    ComposedRuntimeLaunchContextResolver,
    DatabaseSnapshotToolApprovalResolver,
    DynamicRuntimeApplication,
    DynamicRuntimeApplicationConfig,
    DynamicRuntimeServicesFactory,
    DynamicRuntimeSupervisor,
    DynamicRuntimeSupervisorConfig,
    ExecutionRouter,
    ExplicitMCPToolCapabilityRuntimeAdapter,
    ExplicitToolCapabilityRuntimeAdapter,
    FileSystemPromptProvider,
    MCPToolProjectionMaterializer,
    OutboxDeliveryPolicy,
    OutboxPublisher,
    PolicyRuntimeClock,
    RuntimeEventBroadcaster,
    RuntimeEventStreamConfig,
    SnapshotCapabilityInstructionRenderer,
    SnapshotToolRegistryFactory,
    StructuredRouteAnalyzer,
    ToolProjectionMaterializer,
)
from agent_factory.dynamic_runtime.application import DynamicRuntimeStores
from agent_factory.dynamic_runtime.runtime_infrastructure import (
    ConversationWorkspaceLaunchResolver,
    PythonModuleToolEntrypointResolver,
    SharedToolOutputResolver,
    SnapshotRuntimeResourceProjector,
    UnavailableAttachmentLaunchResolver,
    UnavailableMCPEntrypointResolver,
    runtime_resource_factory,
)
from agent_factory.model_pool import ModelPoolStore
from agent_factory.paths import factory_artifact_path, project_root
from agent_factory.resource_system import ResourceStore
from agent_factory.runtime_kernel.context.engine import ContextEngine
from agent_factory.runtime_kernel.persistence import (
    LangGraphCheckpointerConfig,
    LangGraphCheckpointerFactory,
    LangGraphStoreConfig,
    LangGraphStoreFactory,
    close_shared_sqlite_checkpointers,
)


@dataclass(frozen=True, slots=True)
class RuntimeBackendConfig:
    database_path: Path
    checkpoint_path: Path
    memory_store_path: Path
    resource_store_path: Path
    tool_output_root: Path
    workspace_root: Path
    main_prompt_path: Path
    router_prompt_path: Path
    build_revision: str
    generation_lease_seconds: int = 30
    command_worker_count: int = 4
    idle_poll_seconds: float = 0.25
    generation_renew_seconds: float = 10.0
    subscriber_queue_capacity: int = 256
    outbox_max_attempts: int = 8
    outbox_retry_delay_seconds: float = 1.0
    maximum_argument_revisions: int = 3

    @classmethod
    def local(cls) -> "RuntimeBackendConfig":
        prompts = project_root() / "agent_factory" / "dynamic_runtime" / "prompts"
        return cls(
            database_path=factory_artifact_path("dynamic_runtime", "runtime.sqlite"),
            checkpoint_path=factory_artifact_path("dynamic_runtime", "checkpoints.sqlite"),
            memory_store_path=factory_artifact_path("memory", "runtime.sqlite"),
            resource_store_path=factory_artifact_path("resources", "runtime.sqlite"),
            tool_output_root=factory_artifact_path("tool_outputs"),
            workspace_root=factory_artifact_path("workspaces"),
            main_prompt_path=prompts / "main_agent.md",
            router_prompt_path=prompts / "execution_router.md",
            build_revision=__version__,
        )


class RuntimeBackend:
    def __init__(self, config: RuntimeBackendConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.broadcaster = RuntimeEventBroadcaster(
            RuntimeEventStreamConfig(
                subscriber_queue_capacity=config.subscriber_queue_capacity,
            )
        )
        self.application = self._open_application()
        dispatcher = self.application.main_command_dispatcher(
            execution_router=ExecutionRouter(
                StructuredRouteAnalyzer.from_file(config.router_prompt_path)
            )
        )
        publisher = OutboxPublisher(
            store=self.application.stores.outbox,
            sink=self.broadcaster,
            policy=OutboxDeliveryPolicy(
                max_attempts=config.outbox_max_attempts,
                retry_delay_seconds=config.outbox_retry_delay_seconds,
            ),
        )
        self.supervisor = DynamicRuntimeSupervisor(
            application=self.application,
            dispatcher=dispatcher,
            outbox_publisher=publisher,
            config=DynamicRuntimeSupervisorConfig(
                command_worker_count=config.command_worker_count,
                idle_poll_seconds=config.idle_poll_seconds,
                generation_renew_seconds=config.generation_renew_seconds,
            ),
            report_failure=self._report_failure,
        )

    def start(self) -> None:
        self.supervisor.start()

    async def stop(self) -> None:
        await self.supervisor.stop()
        self.application.close()
        close_shared_sqlite_checkpointers(under_root=factory_artifact_path())

    def _open_application(self) -> DynamicRuntimeApplication:
        config = self.config
        checkpointer = LangGraphCheckpointerFactory().build(
            LangGraphCheckpointerConfig(backend="sqlite", path=config.checkpoint_path)
        ).saver
        memory_store = LangGraphStoreFactory().build(
            LangGraphStoreConfig(backend="sqlite", path=config.memory_store_path)
        ).store
        context_system = default_context_runtime()

        def services(stores: DynamicRuntimeStores) -> DynamicRuntimeServicesFactory:
            approvals = DatabaseSnapshotToolApprovalResolver(stores.capability_approval_grants)
            outputs = SharedToolOutputResolver(config.tool_output_root)
            resources = SnapshotRuntimeResourceProjector(
                resource_store=ResourceStore(config.resource_store_path),
                runtime_resource_factories={
                    name: runtime_resource_factory(stores.conversations, name)
                    for name in ("filesystem", "process_runtime", "runtime_identity")
                },
            )
            tool_adapter = ExplicitToolCapabilityRuntimeAdapter(
                entrypoints=PythonModuleToolEntrypointResolver(),
                resources=resources,
                outputs=outputs,
                approvals=approvals,
                maximum_argument_revisions=config.maximum_argument_revisions,
            )
            mcp_adapter = ExplicitMCPToolCapabilityRuntimeAdapter(
                entrypoints=UnavailableMCPEntrypointResolver(),
                outputs=outputs,
                approvals=approvals,
                maximum_argument_revisions=config.maximum_argument_revisions,
            )
            registry_factory = SnapshotToolRegistryFactory(
                (
                    ToolProjectionMaterializer(tool_adapter),
                    MCPToolProjectionMaterializer(mcp_adapter),
                )
            )
            return DynamicRuntimeServicesFactory(
                snapshot_tool_registries=registry_factory,
                checkpointer=checkpointer,
                memory_store=memory_store,
                context_system=context_system,
                context_engine=ContextEngine(),
            )

        def launch_context(stores: DynamicRuntimeStores) -> ComposedRuntimeLaunchContextResolver:
            return ComposedRuntimeLaunchContextResolver(
                prompt_provider=FileSystemPromptProvider(config.main_prompt_path),
                clock=PolicyRuntimeClock(),
                workspaces=ConversationWorkspaceLaunchResolver(stores.conversations),
                attachments=UnavailableAttachmentLaunchResolver(),
                capability_instructions=SnapshotCapabilityInstructionRenderer(),
            )

        return DynamicRuntimeApplication.open(
            config=DynamicRuntimeApplicationConfig(
                database_path=config.database_path,
                build_revision=config.build_revision,
                generation_lease_seconds=config.generation_lease_seconds,
                capability_resolution=CapabilityResolutionConfig(
                    search=CapabilitySearchConfig(
                        maximum_results=24,
                        minimum_score=0.05,
                        display_name_weight=0.35,
                        description_weight=0.35,
                        keyword_weight=0.3,
                        exact_phrase_bonus=0.2,
                    ),
                    host_platform=_host_platform(),
                    host_python_abi=str(sys.implementation.cache_tag or "") or None,
                    allowed_trust_levels=("builtin", "local_user", "verified_external"),
                ),
            ),
            services_factory=services,
            model_pool_store=ModelPoolStore(),
            launch_context_resolver=launch_context,
        )

    def _report_failure(self, component: str, error: BaseException) -> None:
        self.logger.error(
            "Dynamic runtime component failed: %s: %s",
            component,
            error,
            exc_info=(type(error), error, error.__traceback__),
        )


def _host_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    if system == "windows" and machine in {"amd64", "x86_64"}:
        return "windows-x86_64"
    if system == "linux" and machine in {"amd64", "x86_64"}:
        return "linux-x86_64"
    raise RuntimeError(f"unsupported dynamic runtime platform: {system}/{machine}")
