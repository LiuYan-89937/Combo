from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import StringIO
import logging
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
from threading import RLock
from typing import Any, Callable
from uuid import uuid4
from ruamel.yaml import YAML

from agent_factory import __version__
from agent_factory.context_system.runtime import default_context_runtime
from agent_factory.dynamic_runtime import (
    CapabilityResolutionConfig,
    CapabilitySearchConfig,
    ComposedRuntimeLaunchContextResolver,
    DatabaseSnapshotToolApprovalResolver,
    DynamicRuntimeApplication,
    DynamicRuntimeApplicationConfig,
    DynamicRuntimeDatabase,
    DynamicRuntimeMigrationRegistry,
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
    remove_sqlite_database_files,
)
from agent_factory.dynamic_runtime.capability_bootstrap import (
    CapabilityBootstrapConfig,
    CapabilityBootstrapPublisher,
)
from agent_factory.dynamic_runtime.capability_adapters import CapabilityAdapterRegistry
from agent_factory.dynamic_runtime.capability_kind_adapters import default_capability_adapters
from agent_factory.dynamic_runtime.capability_definitions import (
    MCPServerDefinition,
    MCPToolDefinition,
    SkillDefinition,
    ToolDefinition,
)
from agent_factory.dynamic_runtime.capability_catalog_runtime import CapabilityCatalogRuntime
from agent_factory.dynamic_runtime.delegation_runtime import DelegationRuntimeCoordinator
from agent_factory.dynamic_runtime.capability_blob_store import CapabilityBlobStore
from agent_factory.dynamic_runtime.skill_source import (
    FileSystemSkillCapabilitySource,
    FileSystemSkillSourceConfig,
    SkillSourceRoot,
)
from agent_factory.dynamic_runtime.tool_package_source import (
    FileSystemToolCapabilitySource,
    FileSystemToolSourceConfig,
    ToolSourceRoot,
)
from agent_factory.dynamic_runtime.tool_package_runtime import ToolPackageRuntime
from agent_factory.environment_system import DependencyPoolService
from agent_factory.dynamic_runtime.application import DynamicRuntimeStores
from agent_factory.dynamic_runtime.runtime_infrastructure import (
    ConversationWorkspaceLaunchResolver,
    ToolEntrypointResolver,
    SharedToolOutputResolver,
    SnapshotRuntimeResourceProjector,
    RuntimeProcessResourcePool,
    RuntimeFilesystemResourcePool,
    RevisionBoundMCPEntrypointResolver,
    runtime_resource_factory,
)
from agent_factory.model_pool import ModelPoolStore
from agent_factory.paths import factory_artifact_path, project_root
from agent_factory.resource_system import ResourceStore
from agent_factory.runtime_protocol import CommandReceipt
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
from agent_factory.tooling.skillhub.service import SkillHubService
from agent_factory.dynamic_runtime.mcp_runtime import MCPRuntimePool
from agent_factory.dynamic_runtime.mcp_source import MCPConfigCapabilitySource, MCPConfigSourceConfig
from web_frontend.backend.frontend_event_bridge import FrontendEventBridge, RuntimeEventFanout
from web_frontend.backend.attachment_upload_store import StagedAttachmentLaunchResolver


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
    builtin_tool_overrides_path: Path
    skill_capability_source_prefix: str
    capability_blob_root: Path
    skill_source_roots: tuple[SkillSourceRoot, ...]
    maximum_skill_file_bytes: int
    maximum_skill_bytes: int
    tool_capability_source_prefix: str
    tool_source_roots: tuple[ToolSourceRoot, ...]
    maximum_tool_file_bytes: int
    maximum_tool_bytes: int
    tool_package_runtime_root: Path
    mcp_capability_source_prefix: str
    mcp_server_registry_path: Path
    browser_runtime: BrowserRuntimeConfig
    process_environment: tuple[tuple[str, str], ...]
    allowed_frontend_origins: tuple[str, ...]
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
            builtin_tool_overrides_path=factory_artifact_path(
                "extension_registry", "builtin_tool_overrides.json"
            ),
            skill_capability_source_prefix="filesystem-skill://",
            capability_blob_root=factory_artifact_path("capability_blobs"),
            skill_source_roots=(
                SkillSourceRoot(
                    root_id="local-skills",
                    path=factory_artifact_path("extension_registry", "skills"),
                    trust_level="local_user",
                ),
            ),
            maximum_skill_file_bytes=4 * 1024 * 1024,
            maximum_skill_bytes=32 * 1024 * 1024,
            tool_capability_source_prefix="filesystem-tool://",
            tool_source_roots=(
                ToolSourceRoot(
                    root_id="local-tools",
                    path=factory_artifact_path("extension_registry", "tools"),
                    trust_level="local_user",
                ),
            ),
            maximum_tool_file_bytes=8 * 1024 * 1024,
            maximum_tool_bytes=64 * 1024 * 1024,
            tool_package_runtime_root=factory_artifact_path("tool_package_runtime"),
            mcp_capability_source_prefix="mcp-config://",
            mcp_server_registry_path=factory_artifact_path(
                "extension_registry", "mcp_servers.json"
            ),
            browser_runtime=_browser_runtime_config(),
            process_environment=_process_environment(),
            allowed_frontend_origins=_allowed_frontend_origins(),
        )


class RuntimeBackend:
    def __init__(self, config: RuntimeBackendConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        _initialize_capability_storage(config)
        self.frontend_events = FrontendEventBridge(
            queue_capacity=config.subscriber_queue_capacity,
        )
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
        self.skillhub_runtime = SkillHubService(
            skills_dir=config.skill_source_roots[0].path,
        )
        self._mcp_registry_lock = RLock()
        self._tool_package_lock = RLock()
        self.tool_package_runtime: ToolPackageRuntime | None = None
        try:
            self.application = self._open_application()
            self.frontend_events.bind_request_id_resolver(self._frontend_request_id)
            self.frontend_events.bind_active_request_resolver(self._active_frontend_requests)
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
            sink=RuntimeEventFanout(
                self.broadcaster,
                self.frontend_events,
                lambda runtime_instance_id: (
                    self.application.stores.runtime_instances
                    .get(runtime_instance_id)
                    .request.principal_id
                ),
            ),
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

    def _frontend_request_id(self, runtime_instance_id: str, fallback: str) -> str:
        with self.application.database.connection(query_only=True) as connection:
            row = connection.execute(
                """
                select command_id from command_inbox
                where json_extract(receipt_json, '$.runtime_instance_id') = ?
                order by updated_at desc limit 1
                """,
                (runtime_instance_id,),
            ).fetchone()
        return str(row["command_id"]) if row is not None else fallback

    def _active_frontend_requests(self, principal_id: str) -> list[dict[str, Any]]:
        with self.application.database.connection(query_only=True) as connection:
            rows = connection.execute(
                """
                select * from (
                  select command_id, session_id, status, receipt_json,
                         queue_sequence, received_at, updated_at,
                         (
                           select runtime.status from runtime_instances as runtime
                           where runtime.runtime_instance_id = json_extract(
                             command_inbox.receipt_json,
                             '$.runtime_instance_id'
                           )
                         ) as runtime_status
                  from command_inbox
                  where principal_id = ? and command_kind = 'send_message'
                )
                where status in ('queued', 'running')
                   or runtime_status in ('waiting_approval', 'waiting_external')
                order by queue_sequence
                """,
                (principal_id,),
            ).fetchall()
        queued_positions: dict[str, int] = {}
        values: list[dict[str, Any]] = []
        for row in rows:
            session_id = str(row["session_id"])
            status = str(row["status"])
            runtime_status = str(row["runtime_status"] or "")
            queue_position = 0
            if status == "queued":
                queue_position = queued_positions.get(session_id, 0) + 1
                queued_positions[session_id] = queue_position
            receipt = CommandReceipt.model_validate_json(str(row["receipt_json"]))
            dispatch_state = self._active_request_dispatch_state(
                command_status=status,
                runtime_status=runtime_status,
            )
            values.append(
                {
                    "request_id": str(row["command_id"]),
                    "status": "running",
                    "mode": "agent_package",
                    "run_id": receipt.runtime_instance_id,
                    "background": False,
                    "source": "user",
                    "started_at": str(row["received_at"]),
                    "completed_at": None,
                    "payload": {
                        "dispatch_state": dispatch_state,
                        "queue_position": queue_position,
                        "runtime_status": runtime_status or None,
                        "session_id": session_id,
                        "agent_session_id": session_id,
                        "package_id": "factory_chat",
                    },
                }
            )
        return values

    @staticmethod
    def _active_request_dispatch_state(*, command_status: str, runtime_status: str) -> str:
        if command_status == "queued":
            return "queued"
        if runtime_status in {"waiting_approval", "waiting_external"}:
            return runtime_status
        return "running"

    def start(self) -> None:
        self.supervisor.start()

    def capability_pool_snapshot(self) -> dict[str, object]:
        capabilities: list[dict[str, object]] = []
        counts = {"skill": 0, "tool": 0, "mcp_server": 0, "mcp_tool": 0}
        vector_index = self.application.capability_search.active_vector_index_status()
        for item in self.application.stores.capabilities.active_capabilities():
            revision = item.revision
            if revision.kind not in counts:
                continue
            counts[revision.kind] += 1
            health = self.application.stores.capability_resolution_receipts.latest_health(
                capability_id=revision.capability_id,
                revision=revision.revision,
                content_digest=revision.content_digest,
            )
            capabilities.append(
                {
                    "capability_id": revision.capability_id,
                    "kind": revision.kind,
                    "namespace": revision.namespace,
                    "display_name": revision.content.display_name,
                    "description": revision.content.description,
                    "keywords": list(revision.content.keywords),
                    "revision": revision.revision,
                    "resolved_version": revision.resolved_version,
                    "content_digest": revision.content_digest,
                    "source_uri": revision.source_uri,
                    "trust_level": revision.trust_level,
                    "health": None if health is None else health.status,
                    "indexing": {
                        "vector": (
                            vector_index is not None
                            and revision.capability_id in vector_index.capability_ids
                        ),
                        "generation_id": (
                            vector_index.generation_id if vector_index is not None else None
                        ),
                        "embedding_profile_id": (
                            vector_index.profile_id if vector_index is not None else None
                        ),
                    },
                    "definition_schema": revision.content.definition_schema,
                    "details": _capability_public_details(
                        revision.kind,
                        revision.content.definition,
                    ),
                }
            )
            if revision.kind == "skill":
                skill_parts = revision.capability_id.removeprefix("skill://").split("/", 1)
                if len(skill_parts) == 2:
                    source_root = next((root for root in self.config.skill_source_roots if root.root_id == skill_parts[0]), None)
                    if source_root is not None:
                        capabilities[-1]["details"] = {
                            **dict(capabilities[-1]["details"]),
                            "source_path": str(source_root.path / skill_parts[1]),
                        }
            if revision.kind == "tool" and revision.trust_level == "local_user":
                tool_parts = revision.capability_id.removeprefix("tool://").split("/", 1)
                if len(tool_parts) == 2:
                    source_root = next(
                        (root for root in self.config.tool_source_roots if root.root_id == tool_parts[0]),
                        None,
                    )
                    if source_root is not None:
                        capabilities[-1]["details"] = {
                            **dict(capabilities[-1]["details"]),
                            "source_path": str(source_root.path / tool_parts[1]),
                        }
        capabilities.sort(key=lambda value: (str(value["kind"]), str(value["namespace"])))
        registry = _read_mcp_registry(self.config.mcp_server_registry_path)
        registry_servers = {
            str(server.get("server_id")): server
            for server in registry["servers"]
        }
        for capability in capabilities:
            if capability["kind"] != "mcp_server":
                continue
            server_id = str(capability["capability_id"]).removeprefix("mcp-server://")
            registry_config = registry_servers.get(server_id)
            if registry_config is not None:
                capability["details"] = {
                    **dict(capability["details"]),
                    "registry_config": registry_config,
                }
        return {
            "counts": counts,
            "capabilities": capabilities,
            "mcp_registry_digest": _json_digest(registry),
        }

    def refresh_capability_search_embeddings(self) -> None:
        self.application.capability_search.refresh(
            self.application.stores.capabilities.active_capabilities()
        )

    def _refresh_capability_search_if_ready(self) -> None:
        application = getattr(self, "application", None)
        if application is not None:
            application.capability_search.refresh(
                application.stores.capabilities.active_capabilities()
            )

    def probe_mcp_server(self, capability_id: str) -> dict[str, object]:
        matches = tuple(
            item
            for item in self.application.stores.capabilities.active_capabilities()
            if item.revision.capability_id == capability_id
            and item.revision.kind == "mcp_server"
        )
        if len(matches) != 1:
            raise LookupError(f"active MCP server capability not found: {capability_id}")
        revision = matches[0].revision
        try:
            tools = self.mcp_runtime.discover_tools(revision.content_digest)
        except BaseException as exc:
            self.logger.warning("MCP probe failed for %s: %s", capability_id, exc)
            raise
        return {
            "capability_id": capability_id,
            "content_digest": revision.content_digest,
            "tool_count": len(tools),
            "tools": [str(tool.name) for tool in tools],
        }

    def skillhub_status(self) -> dict[str, Any]:
        return self.skillhub_runtime.status()

    def search_skillhub(self, query: str) -> dict[str, Any]:
        return self.skillhub_runtime.search(query)

    def install_skillhub_skill(self, skill: str) -> dict[str, object]:
        result = self.skillhub_runtime.install(skill)
        return {
            "skillhub": result,
            "capability_pool": self.capability_pool_snapshot(),
        }

    def add_mcp_server(
        self,
        server: dict[str, Any],
        *,
        expected_registry_digest: str,
    ) -> dict[str, object]:
        with self._mcp_registry_lock:
            path = self.config.mcp_server_registry_path
            current = _read_mcp_registry(path)
            if _json_digest(current) != expected_registry_digest:
                raise RuntimeError("mcp_registry_revision_conflict")
            servers = current["servers"]
            server_id = str(server["server_id"])
            if any(str(item.get("server_id")) == server_id for item in servers):
                raise ValueError(f"MCP server already exists: {server_id}")
            replacement = {**current, "servers": [*servers, server]}
            _write_mcp_registry(path, replacement)
            try:
                self._synchronize_mcp_capabilities(
                    self.application.stores,
                    _capability_adapters(),
                )
            except BaseException:
                _write_mcp_registry(path, current)
                try:
                    self._synchronize_mcp_capabilities(
                        self.application.stores,
                        _capability_adapters(),
                    )
                except BaseException as rollback_error:
                    self.logger.error("MCP registry rollback synchronization failed: %s", rollback_error)
                raise
        return self.capability_pool_snapshot()

    def replace_mcp_server(
        self,
        server_id: str,
        server: dict[str, Any],
        *,
        expected_registry_digest: str,
    ) -> dict[str, object]:
        with self._mcp_registry_lock:
            path = self.config.mcp_server_registry_path
            current = _read_mcp_registry(path)
            if _json_digest(current) != expected_registry_digest:
                raise RuntimeError("mcp_registry_revision_conflict")
            normalized_id = str(server_id or "").strip()
            if str(server.get("server_id") or "").strip() != normalized_id:
                raise ValueError("MCP server identity cannot change")
            matches = [index for index, item in enumerate(current["servers"]) if str(item.get("server_id")) == normalized_id]
            if len(matches) != 1:
                raise LookupError(f"MCP server not found: {normalized_id}")
            servers = list(current["servers"])
            existing = dict(servers[matches[0]])
            existing_source = dict(existing.get("source") or {})
            requested_source = dict(server.get("source") or {})
            editable_fields = (
                "transport", "command", "args", "cwd", "env", "url", "headers",
                "enabled", "risk_level_default", "concurrent_default", "timeout_seconds",
                "connect_timeout_seconds", "max_parallel_requests",
            )
            defaulted_optional_fields = {
                "connect_timeout_seconds": 30.0,
                "max_parallel_requests": 1,
            }
            requested_updates = {
                field: server.get(field)
                for field in editable_fields
                if field in existing
                or field not in defaulted_optional_fields
                or server.get(field) != defaulted_optional_fields[field]
            }
            servers[matches[0]] = {
                **existing,
                **requested_updates,
                "source": {
                    **existing_source,
                    "name": requested_source.get("name"),
                    "description": requested_source.get("description"),
                },
            }
            if servers[matches[0]] == existing:
                return self.capability_pool_snapshot()
            replacement = {**current, "servers": servers}
            _write_mcp_registry(path, replacement)
            try:
                self._synchronize_mcp_capabilities(self.application.stores, _capability_adapters())
            except BaseException:
                _write_mcp_registry(path, current)
                self._synchronize_mcp_capabilities(self.application.stores, _capability_adapters())
                raise
        return self.capability_pool_snapshot()

    def replace_skill(
        self,
        *,
        capability_id: str,
        source_path: str,
        expected_content_digest: str,
    ) -> dict[str, object]:
        active = next(
            (
                item.revision
                for item in self.application.stores.capabilities.active_capabilities()
                if item.revision.capability_id == capability_id and item.revision.kind == "skill"
            ),
            None,
        )
        if active is None:
            raise LookupError(f"active Skill capability not found: {capability_id}")
        if active.content_digest != expected_content_digest:
            raise RuntimeError("skill_revision_conflict")
        identity = capability_id.removeprefix("skill://").split("/", 1)
        if len(identity) != 2:
            raise ValueError("Skill capability identity is invalid")
        source_root = next((root for root in self.config.skill_source_roots if root.root_id == identity[0]), None)
        if source_root is None:
            raise ValueError("Skill source is not editable")
        source = Path(source_path).expanduser().resolve()
        target = (source_root.path / identity[1]).resolve()
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            raise ValueError("Skill source must be a directory containing SKILL.md")
        if source == target:
            return self.capability_pool_snapshot()

        staging_root = Path(tempfile.mkdtemp(prefix=".skill-staging-", dir=source_root.path))
        staged = staging_root / identity[1]
        backup = source_root.path / f".{identity[1]}.backup-{uuid4().hex}"
        try:
            shutil.copytree(source, staged, symlinks=False)
            validation_source = self._skill_capability_source((SkillSourceRoot(
                root_id=source_root.root_id,
                path=staging_root,
                trust_level=source_root.trust_level,
            ),))
            drafts = validation_source.drafts()
            if len(drafts) != 1 or drafts[0].capability_id != capability_id:
                raise ValueError("replacement Skill identity does not match the selected Skill")
            if target.exists():
                os.replace(target, backup)
            os.replace(staged, target)
            try:
                self._synchronize_skill_capabilities(self.application.stores, _capability_adapters())
            except BaseException:
                if target.exists():
                    shutil.rmtree(target)
                if backup.exists():
                    os.replace(backup, target)
                self._synchronize_skill_capabilities(self.application.stores, _capability_adapters())
                raise
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)
        return self.capability_pool_snapshot()

    def import_skill_folder(self, source_path: str) -> dict[str, object]:
        source = Path(source_path).expanduser().resolve()
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            raise ValueError("Skill folder must contain SKILL.md at its root")
        source_root = self.config.skill_source_roots[0]
        staging_root = Path(tempfile.mkdtemp(prefix=".skill-import-", dir=source_root.path))
        staged = staging_root / source.name
        try:
            shutil.copytree(source, staged, symlinks=False)
            validation_source = self._skill_capability_source((SkillSourceRoot(
                root_id=source_root.root_id,
                path=staging_root,
                trust_level=source_root.trust_level,
            ),))
            drafts = validation_source.drafts()
            if len(drafts) != 1:
                raise ValueError("Skill folder must contain exactly one Skill")
            skill_name = drafts[0].capability_id.removeprefix(f"skill://{source_root.root_id}/")
            target = (source_root.path / skill_name).resolve()
            if source_root.path not in target.parents:
                raise ValueError("Skill identity resolves outside the configured Skill source")
            if target.exists():
                raise RuntimeError("skill_already_exists")
            os.replace(staged, target)
            try:
                self._synchronize_skill_capabilities(self.application.stores, _capability_adapters())
            except BaseException:
                shutil.rmtree(target, ignore_errors=True)
                self._synchronize_skill_capabilities(self.application.stores, _capability_adapters())
                raise
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)
        return self.capability_pool_snapshot()

    def import_tool_folder(
        self,
        source_path: str,
        *,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, object]:
        source = Path(source_path).expanduser().resolve()
        if not source.is_dir() or not (source / "TOOL.yaml").is_file() or not (source / "main.py").is_file():
            raise ValueError("Tool folder must contain TOOL.yaml and main.py at its root")
        source_root = self.config.tool_source_roots[0]
        with self._tool_package_lock:
            staging_root = Path(tempfile.mkdtemp(prefix=".tool-import-", dir=source_root.path))
            staged = staging_root / source.name
            target: Path | None = None
            try:
                _report_tool_preparation(on_progress, "validating_tool_package")
                shutil.copytree(source, staged, symlinks=False)
                validation_source = self._tool_capability_source((ToolSourceRoot(
                    root_id=source_root.root_id,
                    path=staging_root,
                    trust_level=source_root.trust_level,
                ),))
                drafts = validation_source.drafts()
                if len(drafts) != 1:
                    raise ValueError("Tool folder must contain exactly one ToolPackage")
                tool_name = drafts[0].capability_id.removeprefix(f"tool://{source_root.root_id}/")
                target = (source_root.path / tool_name).resolve()
                if source_root.path not in target.parents:
                    raise ValueError("ToolPackage identity resolves outside the configured tool source")
                if target.exists():
                    raise RuntimeError("tool_already_exists")
                if self.tool_package_runtime is None:
                    raise RuntimeError("ToolPackage runtime is not initialized")
                definition = ToolDefinition.model_validate(drafts[0].content.definition)
                self.tool_package_runtime.prepare(definition, on_progress=on_progress)
                _report_tool_preparation(on_progress, "validating_tool_import")
                os.replace(staged, target)
                try:
                    _report_tool_preparation(on_progress, "publishing_tool_package")
                    self._synchronize_tool_package_capabilities(
                        self.application.stores,
                        _capability_adapters(),
                    )
                except BaseException:
                    shutil.rmtree(target, ignore_errors=True)
                    self._synchronize_tool_package_capabilities(
                        self.application.stores,
                        _capability_adapters(),
                    )
                    raise
                _report_tool_preparation(on_progress, "tool_package_published")
            finally:
                shutil.rmtree(staging_root, ignore_errors=True)
        return self.capability_pool_snapshot()

    def create_tool_package(
        self,
        payload: dict[str, Any],
        main_source: str,
        *,
        on_progress: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> dict[str, object]:
        """Assemble the internal package format from user-facing tool fields."""

        source_root = self.config.tool_source_roots[0]
        package_name = str(payload["name"])
        input_properties = {
            str(item["name"]): {
                "type": str(item["type"]),
                "description": str(item["description"]),
            }
            for item in payload["parameters"]
        }
        required = [
            str(item["name"])
            for item in payload["parameters"]
            if bool(item["required"])
        ]
        runtime_policy = dict(payload["runtime_policy"])
        manifest = {
            "schema_version": "tool_package.v1",
            "name": package_name,
            "model_alias": str(payload["model_alias"]),
            "display_name": str(payload["display_name"]),
            "description": str(payload["description"]),
            "keywords": list(payload["keywords"]),
            "entrypoint": "main:run",
            "input_schema": {
                "type": "object",
                "properties": input_properties,
                "required": required,
                "additionalProperties": False,
            },
            "output_schema": {"type": "object"},
            "permissions": {
                "approval": runtime_policy["approval"],
                "risk_level": runtime_policy["risk_level"],
                "effects": ["read"],
                "read_only": True,
            },
            "execution": {
                "allow_parallel_calls": runtime_policy["allow_parallel_calls"],
                "max_parallel_calls": runtime_policy["max_parallel_calls"],
                "timeout_seconds": runtime_policy["timeout_seconds"],
                "output_projection": runtime_policy["output_projection"],
                "output_max_model_chars": runtime_policy["output_max_model_chars"],
                "retain_raw_output": runtime_policy["retain_raw_output"],
            },
        }
        staging_parent = Path(tempfile.mkdtemp(prefix="agentfactory-tool-create-"))
        source = staging_parent / package_name
        source.mkdir()
        try:
            _report_tool_preparation(on_progress, "assembling_tool_package")
            yaml = YAML()
            yaml.default_flow_style = False
            stream = StringIO()
            yaml.dump(manifest, stream)
            (source / "TOOL.yaml").write_text(stream.getvalue(), encoding="utf-8")
            (source / "main.py").write_text(str(main_source), encoding="utf-8")
            dependencies = [str(value).strip() for value in payload["dependencies"] if str(value).strip()]
            if dependencies:
                (source / "requirements.txt").write_text("\n".join(dependencies) + "\n", encoding="utf-8")
            return self.import_tool_folder(str(source), on_progress=on_progress)
        finally:
            shutil.rmtree(staging_parent, ignore_errors=True)

    def tool_package_editor_document(self, capability_id: str) -> dict[str, object]:
        active, _, target = self._editable_tool_package(capability_id)
        definition = ToolDefinition.model_validate(active.content.definition)
        files: list[dict[str, object]] = []
        for path in sorted(target.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_dir():
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"ToolPackage content must be a regular file: {path}")
            raw = path.read_bytes()
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                content = None
            files.append({
                "path": path.relative_to(target).as_posix(),
                "size_bytes": len(raw),
                "editable": content is not None,
                "content": content,
            })
        return {
            "capability_id": capability_id,
            "content_digest": active.content_digest,
            "source_path": str(target),
            "entrypoint": definition.implementation.entrypoint,
            "python_requirements": list(definition.implementation.python_requirements),
            "files": files,
        }

    def replace_tool_package_content(
        self,
        *,
        capability_id: str,
        expected_content_digest: str,
        files: dict[str, str],
    ) -> dict[str, object]:
        with self._tool_package_lock:
            active, source_root, target = self._editable_tool_package(capability_id)
            if active.content_digest != expected_content_digest:
                raise RuntimeError("tool_revision_conflict")
            existing = {
                path.relative_to(target).as_posix(): path
                for path in target.rglob("*")
                if path.is_file() and not path.is_symlink()
            }
            normalized: dict[str, str] = {}
            for logical_path, content in files.items():
                path = Path(str(logical_path).replace("\\", "/"))
                if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
                    raise ValueError(f"ToolPackage editor path is invalid: {logical_path}")
                portable = path.as_posix()
                if portable not in existing:
                    raise ValueError(f"ToolPackage editor cannot create undeclared files: {portable}")
                try:
                    existing[portable].read_bytes().decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError(f"ToolPackage editor cannot replace binary content: {portable}") from exc
                normalized[portable] = str(content)
            if not normalized:
                raise ValueError("ToolPackage editor requires at least one text file")

            staging_root = Path(tempfile.mkdtemp(prefix=".tool-edit-", dir=source_root.path))
            staged = staging_root / target.name
            backup = source_root.path / f".{target.name}.backup-{uuid4().hex}"
            try:
                shutil.copytree(target, staged, symlinks=False)
                for logical_path, content in normalized.items():
                    (staged / logical_path).write_text(content, encoding="utf-8")
                validation_source = self._tool_capability_source((ToolSourceRoot(
                    root_id=source_root.root_id,
                    path=staging_root,
                    trust_level=source_root.trust_level,
                ),))
                drafts = validation_source.drafts()
                if len(drafts) != 1 or drafts[0].capability_id != capability_id:
                    raise ValueError("edited ToolPackage identity differs from the published capability")
                if self.tool_package_runtime is None:
                    raise RuntimeError("ToolPackage runtime is not initialized")
                self.tool_package_runtime.prepare(
                    ToolDefinition.model_validate(drafts[0].content.definition)
                )
                os.replace(target, backup)
                os.replace(staged, target)
                try:
                    self._synchronize_tool_package_capabilities(
                        self.application.stores,
                        _capability_adapters(),
                    )
                except BaseException:
                    shutil.rmtree(target, ignore_errors=True)
                    os.replace(backup, target)
                    self._synchronize_tool_package_capabilities(
                        self.application.stores,
                        _capability_adapters(),
                    )
                    raise
                shutil.rmtree(backup, ignore_errors=True)
            finally:
                shutil.rmtree(staging_root, ignore_errors=True)
        return self.capability_pool_snapshot()

    def _editable_tool_package(self, capability_id: str):
        active = next(
            (
                item.revision
                for item in self.application.stores.capabilities.active_capabilities()
                if item.revision.capability_id == capability_id and item.revision.kind == "tool"
            ),
            None,
        )
        if active is None:
            raise LookupError(f"active ToolPackage capability not found: {capability_id}")
        definition = ToolDefinition.model_validate(active.content.definition)
        if definition.implementation.kind != "python_package":
            raise ValueError("selected tool is not an editable ToolPackage")
        identity = capability_id.removeprefix("tool://").split("/", 1)
        if len(identity) != 2:
            raise ValueError("ToolPackage capability identity is invalid")
        source_root = next(
            (root for root in self.config.tool_source_roots if root.root_id == identity[0]),
            None,
        )
        if source_root is None:
            raise ValueError("ToolPackage source is not editable")
        target = (source_root.path / identity[1]).resolve()
        if source_root.path not in target.parents or not (target / "TOOL.yaml").is_file():
            raise ValueError("ToolPackage source is unavailable")
        return active, source_root, target

    def skill_editor_document(self, capability_id: str) -> dict[str, object]:
        active, source_root, target = self._editable_skill(capability_id)
        metadata, instructions = _read_skill_manifest_document(target / "SKILL.md")
        resources: list[dict[str, object]] = []
        for path in sorted(target.rglob("*"), key=lambda item: item.as_posix()):
            if path == target / "SKILL.md" or path.is_dir():
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Skill resource must be a regular file: {path}")
            raw = path.read_bytes()
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError:
                content = None
            resources.append({
                "path": path.relative_to(target).as_posix(),
                "size_bytes": len(raw),
                "editable": content is not None,
                "content": content,
            })
        return {
            "capability_id": capability_id,
            "content_digest": active.content_digest,
            "source_path": str(target),
            "metadata": metadata,
            "instructions": instructions,
            "resources": resources,
        }

    def replace_skill_content(
        self,
        *,
        capability_id: str,
        expected_content_digest: str,
        metadata: dict[str, Any],
        instructions: str,
        resources: dict[str, str],
    ) -> dict[str, object]:
        active, source_root, target = self._editable_skill(capability_id)
        if active.content_digest != expected_content_digest:
            raise RuntimeError("skill_revision_conflict")
        identity_name = capability_id.removeprefix("skill://").split("/", 1)[1]
        normalized_metadata = dict(metadata)
        normalized_metadata["name"] = identity_name
        if not str(normalized_metadata.get("description") or "").strip():
            raise ValueError("Skill description must not be empty")
        normalized_instructions = str(instructions or "").strip()
        if not normalized_instructions:
            raise ValueError("Skill instructions must not be empty")

        staging_root = Path(tempfile.mkdtemp(prefix=".skill-editor-", dir=source_root.path))
        staged = staging_root / identity_name
        backup = source_root.path / f".{identity_name}.backup-{uuid4().hex}"
        try:
            shutil.copytree(target, staged, symlinks=False)
            _write_skill_manifest_document(
                staged / "SKILL.md",
                metadata=normalized_metadata,
                instructions=normalized_instructions,
            )
            for logical_path, content in resources.items():
                relative = Path(str(logical_path).replace("\\", "/"))
                if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
                    raise ValueError(f"Skill resource path is invalid: {logical_path}")
                destination = (staged / relative).resolve()
                if staged.resolve() not in destination.parents or not destination.is_file() or destination.is_symlink():
                    raise ValueError(f"Skill resource is not editable: {logical_path}")
                destination.write_text(str(content), encoding="utf-8")
            validation_source = self._skill_capability_source((SkillSourceRoot(
                root_id=source_root.root_id,
                path=staging_root,
                trust_level=source_root.trust_level,
            ),))
            drafts = validation_source.drafts()
            if len(drafts) != 1 or drafts[0].capability_id != capability_id:
                raise ValueError("edited Skill identity does not match the selected Skill")
            os.replace(target, backup)
            os.replace(staged, target)
            try:
                self._synchronize_skill_capabilities(self.application.stores, _capability_adapters())
            except BaseException:
                if target.exists():
                    shutil.rmtree(target)
                os.replace(backup, target)
                self._synchronize_skill_capabilities(self.application.stores, _capability_adapters())
                raise
            shutil.rmtree(backup)
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)
        return self.capability_pool_snapshot()

    def _editable_skill(self, capability_id: str):
        active = next(
            (
                item.revision
                for item in self.application.stores.capabilities.active_capabilities()
                if item.revision.capability_id == capability_id and item.revision.kind == "skill"
            ),
            None,
        )
        if active is None:
            raise LookupError(f"active Skill capability not found: {capability_id}")
        identity = capability_id.removeprefix("skill://").split("/", 1)
        if len(identity) != 2:
            raise ValueError("Skill capability identity is invalid")
        source_root = next((root for root in self.config.skill_source_roots if root.root_id == identity[0]), None)
        if source_root is None:
            raise ValueError("Skill source is not editable")
        target = (source_root.path / identity[1]).resolve()
        if source_root.path not in target.parents or not (target / "SKILL.md").is_file():
            raise ValueError("Skill source is unavailable")
        return active, source_root, target

    def replace_tool_configuration(
        self,
        *,
        capability_id: str,
        expected_content_digest: str,
        display_name: str,
        description: str,
        runtime_policy: dict[str, Any],
    ) -> dict[str, object]:
        active = next(
            (
                item.revision
                for item in self.application.stores.capabilities.active_capabilities()
                if item.revision.capability_id == capability_id
                and item.revision.kind in {"tool", "mcp_tool"}
            ),
            None,
        )
        if active is None:
            raise LookupError(f"active tool capability not found: {capability_id}")
        if active.content_digest != expected_content_digest:
            raise RuntimeError("tool_revision_conflict")
        current_definition = (
            ToolDefinition.model_validate(active.content.definition)
            if active.kind == "tool"
            else MCPToolDefinition.model_validate(active.content.definition)
        )
        validated_policy = current_definition.runtime_policy.model_validate(runtime_policy)
        normalized_name = str(display_name or "").strip()
        normalized_description = str(description or "").strip()
        if not normalized_name or not normalized_description:
            raise ValueError("tool name and description must not be empty")

        lock = self._tool_package_lock if (
            active.kind == "tool"
            and active.trust_level == "local_user"
            and current_definition.implementation.kind == "python_package"
        ) else self._mcp_registry_lock
        with lock:
            if (
                active.kind == "tool"
                and active.trust_level == "local_user"
                and current_definition.implementation.kind == "python_package"
            ):
                identity = active.capability_id.removeprefix("tool://").split("/", 1)
                if len(identity) != 2:
                    raise ValueError("ToolPackage capability identity is invalid")
                source_root = next(
                    (root for root in self.config.tool_source_roots if root.root_id == identity[0]),
                    None,
                )
                if source_root is None:
                    raise ValueError("ToolPackage source is not editable")
                manifest_path = (source_root.path / identity[1] / "TOOL.yaml").resolve()
                if source_root.path not in manifest_path.parents or not manifest_path.is_file():
                    raise ValueError("ToolPackage source is unavailable")
                previous = manifest_path.read_bytes()
                document = YAML(typ="safe").load(previous.decode("utf-8"))
                if not isinstance(document, dict):
                    raise ValueError("TOOL.yaml must contain an object")
                permissions = dict(document.get("permissions") or {})
                execution = dict(document.get("execution") or {})
                permissions.update({
                    "approval": validated_policy.approval,
                    "risk_level": validated_policy.risk_level,
                })
                execution.update({
                    "allow_parallel_calls": validated_policy.allow_parallel_calls,
                    "max_parallel_calls": validated_policy.max_parallel_calls,
                    "timeout_seconds": validated_policy.timeout_seconds,
                    "output_projection": validated_policy.output_projection,
                    "output_max_model_chars": validated_policy.output_max_model_chars,
                    "retain_raw_output": validated_policy.retain_raw_output,
                })
                document.update({
                    "display_name": normalized_name,
                    "description": normalized_description,
                    "permissions": permissions,
                    "execution": execution,
                })
                _write_yaml_document(manifest_path, document)
                try:
                    drafts = self._tool_capability_source().drafts()
                    replacement = next(
                        draft for draft in drafts if draft.capability_id == active.capability_id
                    )
                    if self.tool_package_runtime is None:
                        raise RuntimeError("ToolPackage runtime is not initialized")
                    self.tool_package_runtime.prepare(
                        ToolDefinition.model_validate(replacement.content.definition)
                    )
                    self._synchronize_tool_package_capabilities(
                        self.application.stores,
                        _capability_adapters(),
                    )
                except BaseException:
                    manifest_path.write_bytes(previous)
                    self._synchronize_tool_package_capabilities(
                        self.application.stores,
                        _capability_adapters(),
                    )
                    raise
            elif active.kind == "tool":
                path = self.config.builtin_tool_overrides_path
                document = _read_builtin_tool_overrides(path)
                alias = current_definition.model_alias
                tools = dict(document["tools"])
                tools[alias] = {
                    "display_name": normalized_name,
                    "description": normalized_description,
                    "runtime_policy": validated_policy.model_dump(mode="json"),
                }
                previous = document
                replacement = {**document, "tools": tools}
                _write_json_document(path, replacement)
                try:
                    self._synchronize_builtin_tool_capabilities(
                        self.application.stores,
                        _capability_adapters(),
                    )
                except BaseException:
                    _write_json_document(path, previous)
                    self._synchronize_builtin_tool_capabilities(
                        self.application.stores,
                        _capability_adapters(),
                    )
                    raise
            else:
                path = self.config.mcp_server_registry_path
                document = _read_mcp_registry(path)
                server_id = active.capability_id.removeprefix("mcp-tool://").split("/", 1)[0]
                matches = [
                    index for index, server in enumerate(document["servers"])
                    if str(server.get("server_id")) == server_id
                ]
                if len(matches) != 1:
                    raise LookupError(f"MCP server not found for tool: {capability_id}")
                servers = list(document["servers"])
                server = dict(servers[matches[0]])
                descriptions = dict(server.get("tool_description_contexts") or {})
                display_names = dict(server.get("tool_display_names") or {})
                policies = dict(server.get("tool_runtime_policies") or {})
                upstream_name = current_definition.upstream_tool_name
                display_names[upstream_name] = normalized_name
                descriptions[upstream_name] = normalized_description
                policies[upstream_name] = validated_policy.model_dump(mode="json")
                server["tool_description_contexts"] = descriptions
                server["tool_display_names"] = display_names
                server["tool_runtime_policies"] = policies
                servers[matches[0]] = server
                replacement = {**document, "servers": servers}
                _write_mcp_registry(path, replacement)
                try:
                    self._synchronize_mcp_capabilities(
                        self.application.stores,
                        _capability_adapters(),
                    )
                except BaseException:
                    _write_mcp_registry(path, document)
                    self._synchronize_mcp_capabilities(
                        self.application.stores,
                        _capability_adapters(),
                    )
                    raise
        return self.capability_pool_snapshot()

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
        migration_registry = DynamicRuntimeMigrationRegistry()
        migration = migration_registry.prepare(DynamicRuntimeDatabase(config.database_path))
        if migration.initialization_required:
            remove_sqlite_database_files(config.checkpoint_path)
            remove_sqlite_database_files(config.graph_store_path)
            if migration.reset_performed:
                self.logger.info(
                    "Reset incompatible dynamic runtime, checkpoint, and graph-store databases "
                    "for schema epoch migration"
                )
        delegation_runtime = DelegationRuntimeCoordinator()
        capability_blobs = CapabilityBlobStore(config.capability_blob_root)
        checkpointer = LangGraphCheckpointerFactory().build(
            LangGraphCheckpointerConfig(backend="sqlite", path=config.checkpoint_path)
        ).saver
        graph_store = LangGraphStoreFactory().build(
            LangGraphStoreConfig(backend="sqlite", path=config.graph_store_path)
        ).store
        def services(stores: DynamicRuntimeStores, capability_search) -> DynamicRuntimeServicesFactory:
            context_system = default_context_runtime(memory_store=stores.memories)
            capability_catalog = CapabilityCatalogRuntime(
                store=stores.capabilities,
                health_receipts=stores.capability_resolution_receipts,
                allowed_trust_levels=("builtin", "local_user", "verified_external"),
                search_index=capability_search,
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
                        delegation_runtime=delegation_runtime,
                        knowledge_store=stores.knowledge,
                        scheduler_store=stores.scheduler,
                        skillhub_runtime=self.skillhub_runtime,
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
                        "delegation_runtime",
                        "knowledge_runtime",
                        "scheduler_runtime",
                        "skillhub_runtime",
                    )
                },
            )
            tool_package_runtime = ToolPackageRuntime(
                blobs=capability_blobs,
                runtime_root=config.tool_package_runtime_root,
                dependency_pool=DependencyPoolService(),
                conversations=stores.conversations,
                base_environment=dict(config.process_environment),
            )
            self.tool_package_runtime = tool_package_runtime
            tool_adapter = ExplicitToolCapabilityRuntimeAdapter(
                entrypoints=ToolEntrypointResolver(packages=tool_package_runtime),
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
                attachments=StagedAttachmentLaunchResolver(),
                capability_instructions=SnapshotCapabilityInstructionRenderer(capability_blobs),
                delegations=stores.delegations,
            )

        def bootstrap_capabilities(stores, adapters) -> None:
            stores.conversations.create_principal(config.capability_publisher_principal_id)
            self._synchronize_builtin_tool_capabilities(stores, adapters)
            self._synchronize_tool_package_capabilities(stores, adapters)
            self._synchronize_skill_capabilities(stores, adapters)
            self._synchronize_mcp_capabilities(stores, adapters)

        application = DynamicRuntimeApplication.open(
            config=DynamicRuntimeApplicationConfig(
                database_path=config.database_path,
                build_revision=config.build_revision,
                generation_lease_seconds=config.generation_lease_seconds,
                capability_resolution=CapabilityResolutionConfig(
                    search=CapabilitySearchConfig(
                        maximum_results=24,
                        minimum_score=0.05,
                        reciprocal_rank_constant=60,
                        lexical_weight=0.55,
                        vector_weight=0.45,
                        exact_match_bonus=0.2,
                        receipt_retention_limit=10_000,
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
            observation_sink=self._publish_runtime_observation,
            migration_registry=migration_registry,
        )
        delegation_runtime.bind(
            delegations=application.stores.delegations,
            model_resolver=application.model_resolver,
            capability_resolver=application.capability_resolver,
            generation=application.generation.generation,
        )
        self.skillhub_runtime.bind_publisher(
            lambda: self._synchronize_skill_capabilities(
                application.stores,
                _capability_adapters(),
            )
        )
        return application

    def _publish_runtime_observation(self, instance, chunk) -> None:
        if instance.request.runtime_role == "temporary":
            self.application.stores.delegations.record_runtime_observation(instance, chunk)
        self.frontend_events.publish_observation(instance, chunk)

    def _synchronize_builtin_tool_capabilities(self, stores, adapters) -> None:
        config = self.config
        source_config = BuiltinToolSourceConfig(
            build_revision=config.build_revision,
            publisher_principal_id=config.capability_publisher_principal_id,
            source_prefix=config.builtin_capability_source_prefix,
            overrides_path=config.builtin_tool_overrides_path,
        )
        CapabilityBootstrapPublisher(
            config=CapabilityBootstrapConfig(
                publisher_principal_id=config.capability_publisher_principal_id,
                managed_source_prefix=config.builtin_capability_source_prefix,
            ),
            store=stores.capabilities,
            resolution_receipts=stores.capability_resolution_receipts,
            adapters=adapters,
        ).synchronize(
            BuiltinToolCapabilitySource(
                source_config,
                blobs=CapabilityBlobStore(config.capability_blob_root),
            ).drafts()
        )
        self._refresh_capability_search_if_ready()

    def _skill_capability_source(
        self,
        roots: tuple[SkillSourceRoot, ...] | None = None,
    ) -> FileSystemSkillCapabilitySource:
        config = self.config
        return FileSystemSkillCapabilitySource(
            config=FileSystemSkillSourceConfig(
                roots=roots or config.skill_source_roots,
                publisher_principal_id=config.capability_publisher_principal_id,
                source_prefix=config.skill_capability_source_prefix,
                maximum_file_bytes=config.maximum_skill_file_bytes,
                maximum_skill_bytes=config.maximum_skill_bytes,
            ),
            blobs=CapabilityBlobStore(config.capability_blob_root),
        )

    def _tool_capability_source(
        self,
        roots: tuple[ToolSourceRoot, ...] | None = None,
    ) -> FileSystemToolCapabilitySource:
        config = self.config
        return FileSystemToolCapabilitySource(
            config=FileSystemToolSourceConfig(
                roots=roots or config.tool_source_roots,
                publisher_principal_id=config.capability_publisher_principal_id,
                source_prefix=config.tool_capability_source_prefix,
                maximum_file_bytes=config.maximum_tool_file_bytes,
                maximum_tool_bytes=config.maximum_tool_bytes,
            ),
            blobs=CapabilityBlobStore(config.capability_blob_root),
        )

    def _synchronize_tool_package_capabilities(self, stores, adapters) -> None:
        config = self.config
        CapabilityBootstrapPublisher(
            config=CapabilityBootstrapConfig(
                publisher_principal_id=config.capability_publisher_principal_id,
                managed_source_prefix=config.tool_capability_source_prefix,
            ),
            store=stores.capabilities,
            resolution_receipts=stores.capability_resolution_receipts,
            adapters=adapters,
        ).synchronize(
            self._tool_capability_source().drafts(),
            deactivate_removed_sources=True,
        )
        self._refresh_capability_search_if_ready()

    def _synchronize_skill_capabilities(self, stores, adapters) -> None:
        config = self.config
        CapabilityBootstrapPublisher(
            config=CapabilityBootstrapConfig(
                publisher_principal_id=config.capability_publisher_principal_id,
                managed_source_prefix=config.skill_capability_source_prefix,
            ),
            store=stores.capabilities,
            resolution_receipts=stores.capability_resolution_receipts,
            adapters=adapters,
        ).synchronize(
            self._skill_capability_source().drafts(),
            deactivate_removed_sources=True,
        )
        self._refresh_capability_search_if_ready()

    def _synchronize_mcp_capabilities(self, stores, adapters) -> None:
        config = self.config
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
        drafts = mcp_source.drafts()
        CapabilityBootstrapPublisher(
            config=CapabilityBootstrapConfig(
                publisher_principal_id=config.capability_publisher_principal_id,
                managed_source_prefix=config.mcp_capability_source_prefix,
            ),
            store=stores.capabilities,
            resolution_receipts=stores.capability_resolution_receipts,
            adapters=adapters,
        ).synchronize(
            drafts,
            deactivate_removed_sources=mcp_source.discovery_complete,
        )
        self._refresh_capability_search_if_ready()

    def _report_failure(self, component: str, error: BaseException) -> None:
        self.logger.error(
            "Dynamic runtime component failed: %s: %s",
            component,
            error,
            exc_info=(type(error), error, error.__traceback__),
        )


def _capability_public_details(kind: str, raw_definition: dict[str, Any]) -> dict[str, object]:
    if kind == "skill":
        definition = SkillDefinition.model_validate(raw_definition)
        contents = (definition.instructions, *definition.contents)
        return {
            "content_count": len(contents),
            "total_size_bytes": sum(item.size_bytes for item in contents),
            "content_paths": [item.logical_path for item in contents],
        }
    if kind == "tool":
        definition = ToolDefinition.model_validate(raw_definition)
        return {
            "model_alias": definition.model_alias,
            "approval": definition.runtime_policy.approval,
            "risk_level": definition.runtime_policy.risk_level,
            "allow_parallel_calls": definition.runtime_policy.allow_parallel_calls,
            "max_parallel_calls": definition.runtime_policy.max_parallel_calls,
            "timeout_seconds": definition.runtime_policy.timeout_seconds,
            "output_projection": definition.runtime_policy.output_projection,
            "output_max_model_chars": definition.runtime_policy.output_max_model_chars,
            "retain_raw_output": definition.runtime_policy.retain_raw_output,
            "read_only": definition.read_only,
            "system_available": definition.system_available,
            "effects": list(definition.effects),
            "implementation_kind": definition.implementation.kind,
            "package_file_count": len(definition.implementation.package_files),
            "python_requirements": list(definition.implementation.python_requirements),
        }
    if kind == "mcp_server":
        definition = MCPServerDefinition.model_validate(raw_definition)
        return {
            "transport": definition.transport,
            "executable": definition.executable,
            "arguments": list(definition.arguments),
            "endpoint": definition.endpoint,
            "working_directory_alias": definition.working_directory_alias,
            "connect_timeout_seconds": definition.connect_timeout_seconds,
            "request_timeout_seconds": definition.request_timeout_seconds,
            "max_parallel_requests": definition.max_parallel_requests,
        }
    if kind == "mcp_tool":
        definition = MCPToolDefinition.model_validate(raw_definition)
        return {
            "server_capability_id": definition.server_capability_id,
            "upstream_tool_name": definition.upstream_tool_name,
            "model_alias": definition.model_alias,
            "approval": definition.runtime_policy.approval,
            "risk_level": definition.runtime_policy.risk_level,
            "allow_parallel_calls": definition.runtime_policy.allow_parallel_calls,
            "max_parallel_calls": definition.runtime_policy.max_parallel_calls,
            "timeout_seconds": definition.runtime_policy.timeout_seconds,
            "output_projection": definition.runtime_policy.output_projection,
            "output_max_model_chars": definition.runtime_policy.output_max_model_chars,
            "retain_raw_output": definition.runtime_policy.retain_raw_output,
            "effects": list(definition.effects),
            "input_schema_digest": definition.input_schema.canonical_digest,
            "output_schema_digest": definition.output_schema.canonical_digest,
        }
    return {}


def _capability_adapters() -> CapabilityAdapterRegistry:
    adapters = CapabilityAdapterRegistry.build(default_capability_adapters())
    adapters.require_complete()
    return adapters


def _read_mcp_registry(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") != "mcp_servers.v0":
        raise ValueError("MCP registry must use mcp_servers.v0")
    servers = document.get("servers")
    if not isinstance(servers, list) or any(not isinstance(item, dict) for item in servers):
        raise ValueError("MCP registry servers must be an array of objects")
    return document


def _write_mcp_registry(path: Path, document: dict[str, Any]) -> None:
    _write_json_document(path, document, temporary_prefix="mcp-registry-")


def _initialize_capability_storage(config: RuntimeBackendConfig) -> None:
    for source_root in config.skill_source_roots:
        source_root.path.mkdir(parents=True, exist_ok=True)
    for source_root in config.tool_source_roots:
        source_root.path.mkdir(parents=True, exist_ok=True)
    config.builtin_tool_overrides_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path = config.mcp_server_registry_path
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with registry_path.open("x", encoding="utf-8") as stream:
            json.dump(
                {"version": "mcp_servers.v0", "servers": []},
                stream,
                ensure_ascii=False,
                indent=2,
            )
            stream.write("\n")
    except FileExistsError:
        pass


def _read_builtin_tool_overrides(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": "builtin_tool_overrides.v1", "tools": {}}
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") != "builtin_tool_overrides.v1":
        raise ValueError("builtin tool overrides must use builtin_tool_overrides.v1")
    tools = document.get("tools")
    if not isinstance(tools, dict) or any(not isinstance(item, dict) for item in tools.values()):
        raise ValueError("builtin tool overrides tools must be an object")
    return document


def _write_json_document(
    path: Path,
    document: dict[str, Any],
    *,
    temporary_prefix: str = "capability-config-",
) -> None:
    serialized = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=temporary_prefix, dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_yaml_document(path: Path, document: dict[str, Any]) -> None:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    stream = StringIO()
    yaml.dump(document, stream)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix="tool-manifest-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(stream.getvalue())
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_digest(value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode("utf-8")).hexdigest()


def _report_tool_preparation(
    callback: Callable[[str, dict[str, Any]], None] | None,
    stage: str,
    **detail: Any,
) -> None:
    if callback is not None:
        callback(stage, detail)


def _read_skill_manifest_document(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md requires YAML front matter")
    try:
        closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("SKILL.md YAML front matter is not closed") from exc
    loaded = YAML(typ="safe").load("\n".join(lines[1:closing])) or {}
    if not isinstance(loaded, dict):
        raise ValueError("SKILL.md front matter must be an object")
    instructions = "\n".join(lines[closing + 1:]).strip()
    return {str(key): value for key, value in loaded.items()}, instructions


def _write_skill_manifest_document(
    path: Path,
    *,
    metadata: dict[str, Any],
    instructions: str,
) -> None:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.allow_unicode = True
    stream = StringIO()
    yaml.dump(metadata, stream)
    path.write_text(f"---\n{stream.getvalue()}---\n\n{instructions.strip()}\n", encoding="utf-8")


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


def _allowed_frontend_origins() -> tuple[str, ...]:
    configured = os.getenv("AGENTFACTORY_FRONTEND_ORIGINS")
    if configured is not None:
        return tuple(origin.strip() for origin in configured.split(",") if origin.strip())
    return (
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    )


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
