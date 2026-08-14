from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from collections.abc import Callable
from typing import Mapping

from combo.dynamic_runtime.capability_adapters import CapabilityAdapterRegistry
from combo.dynamic_runtime.capability_kind_adapters import default_capability_adapters
from combo.dynamic_runtime.capability_resolution_services import (
    ActiveCapabilityPolicyEvaluator,
    CapabilityResolutionConfig,
    PublishedCapabilityCompatibilityResolver,
    ReceiptBackedCapabilityHealthResolver,
    ReceiptBackedDependencyEnvironmentResolver,
)
from combo.dynamic_runtime.capability_resolution_store import (
    CapabilityResolutionReceiptStore,
)
from combo.dynamic_runtime.database import DynamicRuntimeDatabase, DynamicRuntimeMigrationRegistry
from combo.dynamic_runtime.capability_store import CapabilityStore
from combo.dynamic_runtime.approval_store import CapabilityApprovalGrantStore
from combo.dynamic_runtime.capability_resolver import MainTurnCapabilityResolver
from combo.dynamic_runtime.capability_search import (
    CapabilityEmbeddingRuntime,
    HybridCapabilitySearchIndex,
)
from combo.dynamic_runtime.cancellation import (
    CancelRuntimeCommandHandler,
    RuntimeCancellationStore,
)
from combo.dynamic_runtime.command_control import CancelCommandRequestHandler
from combo.dynamic_runtime.control_plane_store import GlobalKnowledgeStore, WorkspaceSchedulerStore
from combo.dynamic_runtime.knowledge_search import HybridKnowledgeSearchIndex
from combo.dynamic_runtime.dispatcher import (
    CommandDispatcher,
    CommandExecutionRegistry,
    CommandHandler,
)
from combo.dynamic_runtime.execution_commits import RuntimeExecutionCommitStore
from combo.dynamic_runtime.delegation_store import DelegationStore
from combo.dynamic_runtime.lifecycle_repositories import (
    DeletePlanStore,
    DeliveryCommitStore,
    RevocationStore,
)
from combo.dynamic_runtime.model_service import RuntimeModelResolver
from combo.dynamic_runtime.memory_store import ScopedMemoryStore
from combo.dynamic_runtime.memory_search import HybridMemorySearchIndex
from combo.dynamic_runtime.main_turn import (
    MainTurnCommandHandler,
)
from combo.dynamic_runtime.policy_repositories import UserRuntimePolicyStore
from combo.dynamic_runtime.policy_commands import SetExecutionPreferenceCommandHandler
from combo.dynamic_runtime.repositories import (
    CommandInbox,
    ConversationStore,
    OutboxStore,
    RuntimeEventStore,
    RuntimeInstanceStore,
    ToolCallStore,
)
from combo.dynamic_runtime.recovery import RuntimeRecoveryReport, RuntimeRecoveryService
from combo.dynamic_runtime.runtime_service import (
    DynamicRuntimeService,
    RuntimeLaunchContextResolver,
    RuntimeObservationSink,
)
from combo.dynamic_runtime.run_control import RuntimeRunControlRegistry
from combo.dynamic_runtime.runtime_start import RuntimeStartStore
from combo.dynamic_runtime.resume import ResumeInterruptCommandHandler
from combo.dynamic_runtime.steering import SteerRuntimeCommandHandler
from combo.dynamic_runtime.services import DynamicRuntimeServiceSet, DynamicRuntimeServicesFactory
from combo.model_pool.store import ModelPoolStore
from combo.models.embedding_model import resolve_embedding_model_profile
from combo.model_pool.usage import ModelUsageStore


@dataclass(frozen=True, slots=True)
class DynamicRuntimeApplicationConfig:
    database_path: Path
    build_revision: str
    capability_resolution: CapabilityResolutionConfig

    def __post_init__(self) -> None:
        path = Path(self.database_path).expanduser().resolve()
        revision = str(self.build_revision or "").strip()
        if not revision:
            raise ValueError("dynamic runtime application requires build_revision")
        object.__setattr__(self, "database_path", path)
        object.__setattr__(self, "build_revision", revision)


@dataclass(frozen=True, slots=True)
class DynamicRuntimeStores:
    capabilities: CapabilityStore
    capability_approval_grants: CapabilityApprovalGrantStore
    capability_resolution_receipts: CapabilityResolutionReceiptStore
    conversations: ConversationStore
    commands: CommandInbox
    runtime_instances: RuntimeInstanceStore
    runtime_events: RuntimeEventStore
    tool_calls: ToolCallStore
    model_usage: ModelUsageStore
    memories: ScopedMemoryStore
    delegations: DelegationStore
    outbox: OutboxStore
    execution_commits: RuntimeExecutionCommitStore
    runtime_starts: RuntimeStartStore
    runtime_policies: UserRuntimePolicyStore
    run_controls: RuntimeRunControlRegistry
    cancellations: RuntimeCancellationStore
    revocations: RevocationStore
    deliveries: DeliveryCommitStore
    delete_plans: DeletePlanStore
    knowledge: GlobalKnowledgeStore
    scheduler: WorkspaceSchedulerStore


class DynamicRuntimeApplication:
    """The single composition root for authoritative dynamic runtime services."""

    def __init__(
        self,
        *,
        config: DynamicRuntimeApplicationConfig,
        database: DynamicRuntimeDatabase,
        stores: DynamicRuntimeStores,
        service_set: DynamicRuntimeServiceSet,
        model_resolver: RuntimeModelResolver,
        capability_resolver: MainTurnCapabilityResolver,
        runtime_service: DynamicRuntimeService,
        recovery_report: RuntimeRecoveryReport,
        capability_search: HybridCapabilitySearchIndex,
    ) -> None:
        self.config = config
        self.database = database
        self.stores = stores
        self.service_set = service_set
        self.model_resolver = model_resolver
        self.capability_resolver = capability_resolver
        self.runtime_service = runtime_service
        self.recovery_report = recovery_report
        self.capability_search = capability_search
        self.command_executions = CommandExecutionRegistry()
        self._closed = False

    @classmethod
    def open(
        cls,
        *,
        config: DynamicRuntimeApplicationConfig,
        services_factory: DynamicRuntimeServicesFactory | Callable[[DynamicRuntimeStores, HybridCapabilitySearchIndex], DynamicRuntimeServicesFactory],
        model_pool_store: ModelPoolStore,
        launch_context_resolver: RuntimeLaunchContextResolver | Callable[[DynamicRuntimeStores], RuntimeLaunchContextResolver],
        capability_bootstrap: Callable[[DynamicRuntimeStores, CapabilityAdapterRegistry], None],
        main_agent_capability_ids: Callable[[], tuple[str, ...]],
        observation_sink: RuntimeObservationSink | None = None,
        migration_registry: DynamicRuntimeMigrationRegistry | None = None,
    ) -> "DynamicRuntimeApplication":
        database = DynamicRuntimeDatabase(config.database_path)
        migrations = migration_registry or DynamicRuntimeMigrationRegistry()
        migrations.migrate(database)
        migrations.verify(database)
        embedding_runtime = _embedding_runtime_resolver(model_pool_store)
        memory_search = HybridMemorySearchIndex(
            database=database,
            embedding_runtime=embedding_runtime,
        )
        knowledge_search = HybridKnowledgeSearchIndex(
            database,
            embedding_runtime=embedding_runtime,
        )
        stores = _stores(database, memory_search=memory_search, knowledge_search=knowledge_search)
        capability_search: HybridCapabilitySearchIndex | None = None
        try:
            capability_search = HybridCapabilitySearchIndex(
                database=database,
                config=config.capability_resolution.search,
                embedding_runtime=embedding_runtime,
            )
            configured_services = services_factory(stores, capability_search) if callable(services_factory) else services_factory
            service_set = configured_services.build()
            model_resolver = RuntimeModelResolver(model_pool_store)
            adapters = CapabilityAdapterRegistry.build(default_capability_adapters())
            adapters.require_complete()
            capability_bootstrap(stores, adapters)
            capability_search.refresh(stores.capabilities.active_capabilities())
            stores.knowledge.refresh_index()
            resolution_config = config.capability_resolution
            capability_resolver = MainTurnCapabilityResolver(
                store=stores.capabilities,
                search_index=capability_search,
                policy_evaluator=ActiveCapabilityPolicyEvaluator(
                    allowed_trust_levels=resolution_config.allowed_trust_levels,
                ),
                compatibility=PublishedCapabilityCompatibilityResolver(
                    host_platform=resolution_config.host_platform,
                    host_python_abi=resolution_config.host_python_abi,
                ),
                health=ReceiptBackedCapabilityHealthResolver(
                    stores.capability_resolution_receipts,
                ),
                dependency_environments=ReceiptBackedDependencyEnvironmentResolver(
                    stores.capability_resolution_receipts,
                ),
                adapters=adapters,
                main_agent_capability_ids=main_agent_capability_ids,
            )
            runtime_service = DynamicRuntimeService(
                service_set=service_set,
                runtime_instances=stores.runtime_instances,
                conversations=stores.conversations,
                execution_commits=stores.execution_commits,
                run_controls=stores.run_controls,
                model_resolver=model_resolver,
                launch_context_resolver=(
                    launch_context_resolver(stores)
                    if callable(launch_context_resolver)
                    else launch_context_resolver
                ),
                delegations=stores.delegations,
                observation_sink=observation_sink,
            )
            recovery_report = RuntimeRecoveryService(database).reconcile()
        except Exception:
            if capability_search is not None:
                capability_search.close()
            memory_search.close()
            knowledge_search.close()
            raise
        return cls(
            config=config,
            database=database,
            stores=stores,
            service_set=service_set,
            model_resolver=model_resolver,
            capability_resolver=capability_resolver,
            runtime_service=runtime_service,
            recovery_report=recovery_report,
            capability_search=capability_search,
        )

    def command_dispatcher(self, handlers: Mapping[str, CommandHandler]) -> CommandDispatcher:
        return CommandDispatcher(
            inbox=self.stores.commands,
            handlers=handlers,
            executions=self.command_executions,
        )

    def main_command_dispatcher(
        self,
        *,
        delegated_model_selector: object | None = None,
    ) -> CommandDispatcher:
        handlers: dict[str, CommandHandler] = {
            "cancel_command_request": CancelCommandRequestHandler(
                commands=self.stores.commands,
                executions=self.command_executions,
            ),
            "send_message": MainTurnCommandHandler(
                conversations=self.stores.conversations,
                runtime_instances=self.stores.runtime_instances,
                runtime_policies=self.stores.runtime_policies,
                model_resolver=self.model_resolver,
                capability_resolver=self.capability_resolver,
                runtime_starts=self.stores.runtime_starts,
                runtime_service=self.runtime_service,
                delegated_model_selector=delegated_model_selector,
            ),
            "set_execution_preference": SetExecutionPreferenceCommandHandler(
                self.stores.runtime_policies
            ),
            "cancel_runtime_request": CancelRuntimeCommandHandler(
                cancellations=self.stores.cancellations,
                run_controls=self.stores.run_controls,
            ),
            "resume_interrupt": ResumeInterruptCommandHandler(
                runtime_instances=self.stores.runtime_instances,
                runtime_service=self.runtime_service,
            ),
            "steer_runtime_request": SteerRuntimeCommandHandler(
                commands=self.stores.commands,
                runtime_instances=self.stores.runtime_instances,
                run_controls=self.stores.run_controls,
            ),
        }
        return self.command_dispatcher(handlers)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.capability_search.close()
        self.stores.memories.close()
        self.stores.knowledge.close()


def _stores(
    database: DynamicRuntimeDatabase,
    *,
    memory_search: HybridMemorySearchIndex,
    knowledge_search: HybridKnowledgeSearchIndex,
) -> DynamicRuntimeStores:
    return DynamicRuntimeStores(
        capabilities=CapabilityStore(database),
        capability_approval_grants=CapabilityApprovalGrantStore(database),
        capability_resolution_receipts=CapabilityResolutionReceiptStore(database),
        conversations=ConversationStore(database),
        commands=CommandInbox(database),
        runtime_instances=RuntimeInstanceStore(database),
        runtime_events=RuntimeEventStore(database),
        tool_calls=ToolCallStore(database),
        model_usage=ModelUsageStore(database),
        memories=ScopedMemoryStore(database, search_index=memory_search),
        delegations=DelegationStore(database),
        outbox=OutboxStore(database),
        execution_commits=RuntimeExecutionCommitStore(database),
        runtime_starts=RuntimeStartStore(database),
        runtime_policies=UserRuntimePolicyStore(database),
        run_controls=RuntimeRunControlRegistry(),
        cancellations=RuntimeCancellationStore(database),
        revocations=RevocationStore(database),
        deliveries=DeliveryCommitStore(database),
        delete_plans=DeletePlanStore(database),
        knowledge=GlobalKnowledgeStore(database, search_index=knowledge_search),
        scheduler=WorkspaceSchedulerStore(database),
    )


def _embedding_runtime_resolver(
    store: ModelPoolStore,
) -> Callable[[], CapabilityEmbeddingRuntime | None]:
    def resolve() -> CapabilityEmbeddingRuntime | None:
        profile_id = store.embedding_binding()
        if not profile_id:
            return None
        resolved = resolve_embedding_model_profile(profile_id, store=store)
        dimensions = resolved.settings.dims
        if dimensions is None:
            raise ValueError("embedding profile must declare dimensions")
        fingerprint_payload = {
            "profile_id": resolved.profile_id,
            "provider": resolved.settings.provider,
            "model": resolved.settings.model,
            "base_url": resolved.settings.base_url,
            "dimensions": dimensions,
            "batch_size": resolved.settings.batch_size,
            "credential_digest": sha256(
                str(resolved.settings.api_key or "").encode("utf-8")
            ).hexdigest(),
        }
        fingerprint = sha256(
            json.dumps(
                fingerprint_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return CapabilityEmbeddingRuntime(
            profile_id=profile_id,
            dimensions=dimensions,
            fingerprint=fingerprint,
            embed_documents=resolved.model.embed_documents,
            embed_query=resolved.model.embed_query,
        )

    return resolve
