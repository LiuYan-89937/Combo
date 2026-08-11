from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from collections.abc import Callable
from typing import Mapping

from agent_factory.dynamic_runtime.capability_adapters import CapabilityAdapterRegistry
from agent_factory.dynamic_runtime.capability_kind_adapters import default_capability_adapters
from agent_factory.dynamic_runtime.capability_resolution_services import (
    ActiveCapabilityPolicyEvaluator,
    CapabilityResolutionConfig,
    PublishedCapabilityCompatibilityResolver,
    PublishedCapabilitySearchIndex,
    ReceiptBackedCapabilityHealthResolver,
    ReceiptBackedDependencyEnvironmentResolver,
)
from agent_factory.dynamic_runtime.capability_resolution_store import (
    CapabilityResolutionReceiptStore,
)
from agent_factory.dynamic_runtime.database import DynamicRuntimeDatabase, DynamicRuntimeMigrationRegistry
from agent_factory.dynamic_runtime.capability_store import CapabilityStore
from agent_factory.dynamic_runtime.approval_store import CapabilityApprovalGrantStore
from agent_factory.dynamic_runtime.capability_resolver import MainTurnCapabilityResolver
from agent_factory.dynamic_runtime.cancellation import (
    CancelRuntimeCommandHandler,
    RuntimeCancellationStore,
)
from agent_factory.dynamic_runtime.dispatcher import CommandDispatcher, CommandHandler
from agent_factory.dynamic_runtime.execution_commits import RuntimeExecutionCommitStore
from agent_factory.dynamic_runtime.lifecycle_repositories import (
    ApplicationGenerationStore,
    CutoverManifestStore,
    DeletePlanStore,
    DeliveryCommitStore,
    RevocationStore,
)
from agent_factory.dynamic_runtime.model_service import RuntimeModelResolver
from agent_factory.dynamic_runtime.main_turn import (
    ExecutionRouter,
    MainTurnCommandHandler,
)
from agent_factory.dynamic_runtime.policy_repositories import UserRuntimePolicyStore
from agent_factory.dynamic_runtime.policy_commands import SetExecutionPreferenceCommandHandler
from agent_factory.dynamic_runtime.repositories import (
    CommandInbox,
    ConversationStore,
    OutboxStore,
    RuntimeEventStore,
    RuntimeInstanceStore,
    ToolCallStore,
)
from agent_factory.dynamic_runtime.recovery import RuntimeRecoveryReport, RuntimeRecoveryService
from agent_factory.dynamic_runtime.runtime_service import DynamicRuntimeService, RuntimeLaunchContextResolver
from agent_factory.dynamic_runtime.run_control import RuntimeRunControlRegistry
from agent_factory.dynamic_runtime.runtime_start import RuntimeStartStore
from agent_factory.dynamic_runtime.resume import ResumeInterruptCommandHandler
from agent_factory.dynamic_runtime.services import DynamicRuntimeServiceSet, DynamicRuntimeServicesFactory
from agent_factory.model_pool.store import ModelPoolStore
from agent_factory.model_pool.usage import ModelUsageStore
from agent_factory.runtime_protocol import ApplicationGeneration
from agent_factory.runtime_protocol.versioning import RUNTIME_PROTOCOL_VERSION, RUNTIME_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class DynamicRuntimeApplicationConfig:
    database_path: Path
    build_revision: str
    generation_lease_seconds: int
    capability_resolution: CapabilityResolutionConfig

    def __post_init__(self) -> None:
        path = Path(self.database_path).expanduser().resolve()
        revision = str(self.build_revision or "").strip()
        if not revision:
            raise ValueError("dynamic runtime application requires build_revision")
        if self.generation_lease_seconds < 1:
            raise ValueError("generation_lease_seconds must be positive")
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
    outbox: OutboxStore
    execution_commits: RuntimeExecutionCommitStore
    runtime_starts: RuntimeStartStore
    runtime_policies: UserRuntimePolicyStore
    run_controls: RuntimeRunControlRegistry
    cancellations: RuntimeCancellationStore
    generations: ApplicationGenerationStore
    cutovers: CutoverManifestStore
    revocations: RevocationStore
    deliveries: DeliveryCommitStore
    delete_plans: DeletePlanStore


class DynamicRuntimeApplication:
    """The single composition root for authoritative dynamic runtime services."""

    def __init__(
        self,
        *,
        config: DynamicRuntimeApplicationConfig,
        database: DynamicRuntimeDatabase,
        stores: DynamicRuntimeStores,
        generation: ApplicationGeneration,
        service_set: DynamicRuntimeServiceSet,
        model_resolver: RuntimeModelResolver,
        capability_resolver: MainTurnCapabilityResolver,
        runtime_service: DynamicRuntimeService,
        recovery_report: RuntimeRecoveryReport,
    ) -> None:
        self.config = config
        self.database = database
        self.stores = stores
        self.generation = generation
        self.service_set = service_set
        self.model_resolver = model_resolver
        self.capability_resolver = capability_resolver
        self.runtime_service = runtime_service
        self.recovery_report = recovery_report

    @classmethod
    def open(
        cls,
        *,
        config: DynamicRuntimeApplicationConfig,
        services_factory: DynamicRuntimeServicesFactory | Callable[[DynamicRuntimeStores], DynamicRuntimeServicesFactory],
        model_pool_store: ModelPoolStore,
        launch_context_resolver: RuntimeLaunchContextResolver | Callable[[DynamicRuntimeStores], RuntimeLaunchContextResolver],
        migration_registry: DynamicRuntimeMigrationRegistry | None = None,
    ) -> "DynamicRuntimeApplication":
        database = DynamicRuntimeDatabase(config.database_path)
        migrations = migration_registry or DynamicRuntimeMigrationRegistry()
        migrations.migrate(database)
        migrations.verify(database)
        stores = _stores(database)
        generation = _starting_generation(config, stores.generations.next_generation_number())
        stores.generations.acquire(generation)
        try:
            configured_services = services_factory(stores) if callable(services_factory) else services_factory
            service_set = configured_services.build()
            model_resolver = RuntimeModelResolver(model_pool_store)
            adapters = CapabilityAdapterRegistry.build(default_capability_adapters())
            resolution_config = config.capability_resolution
            capability_resolver = MainTurnCapabilityResolver(
                store=stores.capabilities,
                search_index=PublishedCapabilitySearchIndex(resolution_config.search),
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
            )
            recovery_report = RuntimeRecoveryService(database).reconcile(
                current_generation=generation.generation,
            )
            active = generation.model_copy(
                update={
                    "status": "active",
                    "updated_at": _utc_now_text(),
                }
            )
            stores.generations.replace(active, expected_status="starting")
        except Exception:
            crashed_at = _utc_now_text()
            crashed = generation.model_copy(
                update={
                    "status": "crashed",
                    "updated_at": crashed_at,
                    "closed_at": crashed_at,
                }
            )
            stores.generations.replace(crashed, expected_status="starting")
            raise
        return cls(
            config=config,
            database=database,
            stores=stores,
            generation=active,
            service_set=service_set,
            model_resolver=model_resolver,
            capability_resolver=capability_resolver,
            runtime_service=runtime_service,
            recovery_report=recovery_report,
        )

    def renew_generation_lease(self) -> ApplicationGeneration:
        current = self.generation
        if current.status != "active":
            raise RuntimeError("cannot renew a generation that is not active")
        now = _utc_now()
        renewed = current.model_copy(
            update={
                "lease_expires_at": _utc_text(now + timedelta(seconds=self.config.generation_lease_seconds)),
                "updated_at": _utc_text(now),
            }
        )
        self.stores.generations.renew(
            renewed,
            expected_lease_expires_at=current.lease_expires_at,
        )
        self.generation = renewed
        return renewed

    def command_dispatcher(self, handlers: Mapping[str, CommandHandler]) -> CommandDispatcher:
        return CommandDispatcher(inbox=self.stores.commands, handlers=handlers)

    def main_command_dispatcher(
        self,
        *,
        execution_router: ExecutionRouter,
    ) -> CommandDispatcher:
        handlers: dict[str, CommandHandler] = {
            "send_message": MainTurnCommandHandler(
                conversations=self.stores.conversations,
                runtime_instances=self.stores.runtime_instances,
                runtime_policies=self.stores.runtime_policies,
                model_resolver=self.model_resolver,
                execution_router=execution_router,
                capability_resolver=self.capability_resolver,
                runtime_starts=self.stores.runtime_starts,
                runtime_service=self.runtime_service,
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
        }
        return self.command_dispatcher(handlers)

    def close(self) -> None:
        current = self.generation
        if current.status in {"closed", "crashed"}:
            return
        now = _utc_now_text()
        if current.status == "active":
            quiescing = current.model_copy(update={"status": "quiescing", "updated_at": now})
            self.stores.generations.replace(quiescing, expected_status="active")
            current = quiescing
        closed = current.model_copy(
            update={
                "status": "closed",
                "updated_at": now,
                "closed_at": now,
            }
        )
        self.stores.generations.replace(closed, expected_status=current.status)
        self.generation = closed


def _stores(database: DynamicRuntimeDatabase) -> DynamicRuntimeStores:
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
        outbox=OutboxStore(database),
        execution_commits=RuntimeExecutionCommitStore(database),
        runtime_starts=RuntimeStartStore(database),
        runtime_policies=UserRuntimePolicyStore(database),
        run_controls=RuntimeRunControlRegistry(),
        cancellations=RuntimeCancellationStore(database),
        generations=ApplicationGenerationStore(database),
        cutovers=CutoverManifestStore(database),
        revocations=RevocationStore(database),
        deliveries=DeliveryCommitStore(database),
        delete_plans=DeletePlanStore(database),
    )


def _starting_generation(config: DynamicRuntimeApplicationConfig, generation: int) -> ApplicationGeneration:
    now = _utc_now()
    return ApplicationGeneration(
        generation=generation,
        build_revision=config.build_revision,
        protocol_version=RUNTIME_PROTOCOL_VERSION,
        schema_version=RUNTIME_SCHEMA_VERSION,
        owner_process_id=os.getpid(),
        lease_expires_at=_utc_text(now + timedelta(seconds=config.generation_lease_seconds)),
        started_at=_utc_text(now),
        updated_at=_utc_text(now),
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_text() -> str:
    return _utc_text(_utc_now())


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()
