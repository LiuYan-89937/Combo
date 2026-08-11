from __future__ import annotations

from dataclasses import dataclass
import logging
import os
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
from agent_factory.dynamic_runtime.capability_bootstrap import (
    CapabilityBootstrapConfig,
    CapabilityBootstrapPublisher,
)
from agent_factory.dynamic_runtime.capability_catalog_runtime import CapabilityCatalogRuntime
from agent_factory.dynamic_runtime.capability_blob_store import CapabilityBlobStore
from agent_factory.dynamic_runtime.skill_source import (
    FileSystemSkillCapabilitySource,
    FileSystemSkillSourceConfig,
    SkillSourceRoot,
)
from agent_factory.dynamic_runtime.application import DynamicRuntimeStores
from agent_factory.dynamic_runtime.runtime_infrastructure import (
    ConversationWorkspaceLaunchResolver,
    PythonModuleToolEntrypointResolver,
    SharedToolOutputResolver,
    SnapshotRuntimeResourceProjector,
    RuntimeProcessResourcePool,
    RuntimeFilesystemResourcePool,
    UnavailableAttachmentLaunchResolver,
    RevisionBoundMCPEntrypointResolver,
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
from agent_factory.tooling.builtins.source import (
    BuiltinToolCapabilitySource,
    BuiltinToolSourceConfig,
)
from agent_factory.tooling.builtins.browser.runtime import BrowserRuntime, BrowserRuntimeConfig
from agent_factory.dynamic_runtime.mcp_runtime import MCPRuntimePool
from agent_factory.dynamic_runtime.mcp_source import MCPConfigCapabilitySource, MCPConfigSourceConfig


@dataclass(frozen=True, slots=True)
class RuntimeBackendConfig:
    database_path: Path
    checkpoint_path: Path
    graph_store_path: Path
    resource_store_path: Path
    tool_output_root: Path
    workspace_root: Path
    main_prompt_path: Path
    router_prompt_path: Path
    build_revision: str
    capability_publisher_principal_id: str
    builtin_capability_source_prefix: str
    skill_capability_source_prefix: str
    capability_blob_root: Path
    skill_source_roots: tuple[SkillSourceRoot, ...]
    maximum_skill_file_bytes: int
    maximum_skill_bytes: int
    mcp_capability_source_prefix: str
    mcp_server_registry_path: Path
    browser_runtime: BrowserRuntimeConfig
    process_environment: tuple[tuple[str, str], ...]
    staged_write_ttl_seconds: int = 600
    workspace_transaction_ttl_seconds: int = 600
    generation_lease_seconds: int = 30
    command_worker_count: int = 4
    temporary_worker_count: int = 4
    temporary_claim_lease_seconds: int = 30
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
            graph_store_path=factory_artifact_path("graph_store", "runtime.sqlite"),
            resource_store_path=factory_artifact_path("resources", "runtime.sqlite"),
            tool_output_root=factory_artifact_path("tool_outputs"),
            workspace_root=factory_artifact_path("workspaces"),
            main_prompt_path=prompts / "main_agent.md",
            router_prompt_path=prompts / "execution_router.md",
            build_revision=__version__,
            capability_publisher_principal_id=f"application-build:{__version__}",
            builtin_capability_source_prefix="builtin-tool://",
            skill_capability_source_prefix="filesystem-skill://",
            capability_blob_root=factory_artifact_path("capability_blobs"),
            skill_source_roots=(
                SkillSourceRoot(
                    root_id="local-skills",
                    path=project_root() / ".agentfactory" / "extension_registry" / "skills",
                    trust_level="local_user",
                ),
            ),
            maximum_skill_file_bytes=4 * 1024 * 1024,
            maximum_skill_bytes=32 * 1024 * 1024,
            mcp_capability_source_prefix="mcp-config://",
            mcp_server_registry_path=(
                project_root() / ".agentfactory" / "extension_registry" / "mcp_servers.json"
            ),
            browser_runtime=_browser_runtime_config(),
            process_environment=_process_environment(),
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
        self.browser_runtime = BrowserRuntime(config.browser_runtime)
        self.process_resources = RuntimeProcessResourcePool(
            environment=dict(config.process_environment)
        )
        self.filesystem_resources = RuntimeFilesystemResourcePool(
            staged_write_ttl_seconds=config.staged_write_ttl_seconds,
            transaction_ttl_seconds=config.workspace_transaction_ttl_seconds,
        )
        self.mcp_runtime = MCPRuntimePool()
        try:
            self.application = self._open_application()
        except BaseException:
            self.browser_runtime.shutdown()
            self.process_resources.close()
            self.filesystem_resources.close()
            self.mcp_runtime.close()
            raise
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
                temporary_worker_count=config.temporary_worker_count,
                temporary_claim_lease_seconds=config.temporary_claim_lease_seconds,
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
        self.browser_runtime.shutdown()
        self.process_resources.close()
        self.filesystem_resources.close()
        self.mcp_runtime.close()
        close_shared_sqlite_checkpointers(under_root=factory_artifact_path())

    def _open_application(self) -> DynamicRuntimeApplication:
        config = self.config
        capability_blobs = CapabilityBlobStore(config.capability_blob_root)
        checkpointer = LangGraphCheckpointerFactory().build(
            LangGraphCheckpointerConfig(backend="sqlite", path=config.checkpoint_path)
        ).saver
        graph_store = LangGraphStoreFactory().build(
            LangGraphStoreConfig(backend="sqlite", path=config.graph_store_path)
        ).store
        def services(stores: DynamicRuntimeStores) -> DynamicRuntimeServicesFactory:
            context_system = default_context_runtime(memory_store=stores.memories)
            capability_catalog = CapabilityCatalogRuntime(
                store=stores.capabilities,
                health_receipts=stores.capability_resolution_receipts,
                allowed_trust_levels=("builtin", "local_user", "verified_external"),
            )
            approvals = DatabaseSnapshotToolApprovalResolver(stores.capability_approval_grants)
            outputs = SharedToolOutputResolver(config.tool_output_root)
            resources = SnapshotRuntimeResourceProjector(
                resource_store=ResourceStore(config.resource_store_path),
                runtime_resource_factories={
                    name: runtime_resource_factory(
                        stores.conversations,
                        name,
                        browser_runtime=self.browser_runtime,
                        capability_catalog=capability_catalog,
                        memory_store=stores.memories,
                        delegations=stores.delegations,
                        process_resources=self.process_resources,
                        filesystem_resources=self.filesystem_resources,
                    )
                    for name in (
                        "filesystem",
                        "process_runtime",
                        "runtime_identity",
                        "browser_runtime",
                        "capability_catalog",
                        "memory_store",
                    )
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
                entrypoints=RevisionBoundMCPEntrypointResolver(self.mcp_runtime),
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
                graph_store=graph_store,
                context_system=context_system,
                context_engine=ContextEngine(),
            )

        def launch_context(stores: DynamicRuntimeStores) -> ComposedRuntimeLaunchContextResolver:
            return ComposedRuntimeLaunchContextResolver(
                prompt_provider=FileSystemPromptProvider(config.main_prompt_path),
                clock=PolicyRuntimeClock(),
                workspaces=ConversationWorkspaceLaunchResolver(stores.conversations),
                attachments=UnavailableAttachmentLaunchResolver(),
                capability_instructions=SnapshotCapabilityInstructionRenderer(capability_blobs),
            )

        def bootstrap_capabilities(stores, adapters) -> None:
            stores.conversations.create_principal(config.capability_publisher_principal_id)
            source_config = BuiltinToolSourceConfig(
                build_revision=config.build_revision,
                publisher_principal_id=config.capability_publisher_principal_id,
                source_prefix=config.builtin_capability_source_prefix,
            )
            CapabilityBootstrapPublisher(
                config=CapabilityBootstrapConfig(
                    publisher_principal_id=config.capability_publisher_principal_id,
                    managed_source_prefix=config.builtin_capability_source_prefix,
                ),
                store=stores.capabilities,
                resolution_receipts=stores.capability_resolution_receipts,
                adapters=adapters,
            ).synchronize(BuiltinToolCapabilitySource(source_config).drafts())
            skill_source = FileSystemSkillCapabilitySource(
                config=FileSystemSkillSourceConfig(
                    roots=config.skill_source_roots,
                    publisher_principal_id=config.capability_publisher_principal_id,
                    source_prefix=config.skill_capability_source_prefix,
                    maximum_file_bytes=config.maximum_skill_file_bytes,
                    maximum_skill_bytes=config.maximum_skill_bytes,
                ),
                blobs=capability_blobs,
            )
            CapabilityBootstrapPublisher(
                config=CapabilityBootstrapConfig(
                    publisher_principal_id=config.capability_publisher_principal_id,
                    managed_source_prefix=config.skill_capability_source_prefix,
                ),
                store=stores.capabilities,
                resolution_receipts=stores.capability_resolution_receipts,
                adapters=adapters,
            ).synchronize(skill_source.drafts())
            mcp_source = MCPConfigCapabilitySource(
                config=MCPConfigSourceConfig(
                    path=config.mcp_server_registry_path,
                    publisher_principal_id=config.capability_publisher_principal_id,
                    source_prefix=config.mcp_capability_source_prefix,
                    base_environment=config.process_environment,
                ),
                runtime=self.mcp_runtime,
                environment_resolver=os.environ.get,
                report_unavailable=lambda server_id, error: self.logger.warning(
                    "Optional MCP server is unavailable during discovery: %s: %s",
                    server_id,
                    error,
                ),
            )
            CapabilityBootstrapPublisher(
                config=CapabilityBootstrapConfig(
                    publisher_principal_id=config.capability_publisher_principal_id,
                    managed_source_prefix=config.mcp_capability_source_prefix,
                ),
                store=stores.capabilities,
                resolution_receipts=stores.capability_resolution_receipts,
                adapters=adapters,
            ).synchronize(mcp_source.drafts())

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
            capability_bootstrap=bootstrap_capabilities,
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


def _process_environment() -> tuple[tuple[str, str], ...]:
    allowed_names = (
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "COMSPEC",
        "PATHEXT",
        "USERPROFILE",
    )
    return tuple(
        (name, value)
        for name in allowed_names
        if (value := os.environ.get(name)) is not None
    )


def _browser_runtime_config() -> BrowserRuntimeConfig:
    return BrowserRuntimeConfig(
        headless=_environment_bool("AGENTFACTORY_BROWSER_HEADLESS", True),
        allow_private_hosts=_environment_bool("AGENTFACTORY_BROWSER_ALLOW_PRIVATE_HOSTS", False),
        default_timeout_ms=_environment_int("AGENTFACTORY_BROWSER_TIMEOUT_MS", 30_000, minimum=1_000),
        navigation_timeout_ms=_environment_int(
            "AGENTFACTORY_BROWSER_NAVIGATION_TIMEOUT_MS", 45_000, minimum=1_000
        ),
        max_contexts=_environment_int("AGENTFACTORY_BROWSER_MAX_CONTEXTS", 24, minimum=1),
        max_pages_per_context=_environment_int("AGENTFACTORY_BROWSER_MAX_PAGES", 12, minimum=1),
        idle_context_seconds=_environment_int(
            "AGENTFACTORY_BROWSER_IDLE_CONTEXT_SECONDS", 1_800, minimum=60
        ),
        viewport_width=_environment_int("AGENTFACTORY_BROWSER_VIEWPORT_WIDTH", 1_440, minimum=320),
        viewport_height=_environment_int("AGENTFACTORY_BROWSER_VIEWPORT_HEIGHT", 900, minimum=240),
        max_snapshot_links=_environment_int(
            "AGENTFACTORY_BROWSER_MAX_SNAPSHOT_LINKS", 200, minimum=1
        ),
        host_validation_ttl_seconds=_environment_int(
            "AGENTFACTORY_BROWSER_HOST_VALIDATION_TTL_SECONDS", 300, minimum=1
        ),
        executable_path=_environment_optional("AGENTFACTORY_BROWSER_EXECUTABLE_PATH"),
    )


def _environment_optional(name: str) -> str | None:
    value = str(os.environ.get(name) or "").strip()
    return value or None


def _environment_bool(name: str, default: bool) -> bool:
    value = str(os.environ.get(name) or "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _environment_int(name: str, default: int, *, minimum: int) -> int:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        return default
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return parsed
