from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from typing import Any, Iterator
from uuid import uuid4

from agent_factory.knowledge_system import KnowledgeRuntime, build_knowledge_runtime
from agent_factory.knowledge_system.schema import KnowledgeContractConfig
from agent_factory.agent_registry import refresh_agent_registry_index
from agent_factory.collaboration_system.store import CollaborationStore
from agent_factory.runtime_contracts import ContextContract, LoadedAgentPackage
from agent_factory.context_system.schema import (
    DEFAULT_COMPRESSION_TRIGGER_TOKEN_THRESHOLD,
    MODEL_COMPRESSION_TRIGGER_TOKENS_ENV,
)
from agent_factory.context_system.token_counter import context_window_tokens_from_env
from agent_factory.runtime_kernel.session import AgentSessionConfig, AgentSessionManager
from agent_factory.runtime_kernel.persistence import delete_sqlite_checkpoint_thread
from agent_factory.runtime_contracts.paths import instance_checkpoint_path
from agent_factory.mcp_gateway import HostMCPGatewayManager
from agent_factory.skillhub_gateway import HostSkillHubGatewayManager
from agent_factory.package_runtime import host_runtime_package_view
from agent_factory.package_runtime.request_lifecycle import RuntimeRequestPolicy
from agent_factory.paths import project_root
from agent_factory.resource_system import ResourceStore, migrate_package_resources
from agent_factory.environment_system import EnvironmentResolver
from agent_factory.runtime_contracts import ResourcesContract
from agent_factory.runtime_attachments import (
    ATTACHMENT_INPUT_DIR,
    AttachmentImportResult,
    import_runtime_attachments,
    time_named_attachment_scope,
)
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import session_payload
from agent_factory.factory_graph.frontend_bridge.agent_runtime_launcher import (
    AgentRuntimeLaunchError,
    DEFAULT_RUNTIME_IMAGE,
    DockerAgentRuntimeLauncher,
    runtime_container_path,
    shutdown_shared_runtime,
)
from agent_factory.factory_graph.frontend_bridge.container_pool import (
    get_global_container_pool,
    shutdown_global_container_pool,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_repository import (
    AgentPackageRepository,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_extensions import (
    AgentPackageExtensionService,
    extensions_summary as _extensions_summary,
    load_extension_bundle as _load_extension_bundle,
    package_extension_detail as _package_extension_detail,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_paths import (
    extension_root_for_package as _extension_root_for_package,
    host_runtime_root as _host_runtime_root,
    host_scratch_workdir as _host_scratch_workdir,
    host_session_workdir as _host_session_workdir,
    host_session_root as _host_session_root,
    is_host_system_package as _is_host_system_package,
    is_system_package as _is_system_package,
    runtime_contract_path as _runtime_contract_path,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_utils import (
    humanize_identifier as _humanize_identifier,
    path_updated_at as _path_updated_at,
    read_json_object as _read_json_object,
)
from agent_factory.factory_graph.frontend_bridge.agent_package_workspace import (
    AgentPackageWorkspaceService,
    workspace_roots,
)
from agent_factory.factory_graph.frontend_bridge.container_runtime_handle import AgentRuntimeContainerHandle
from agent_factory.factory_graph.frontend_bridge.runtime_events import node_event, run_failed_event
from agent_factory.factory_graph.frontend_bridge.system_package_runtime_handle import SystemPackageRuntimeHandle


DEFAULT_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS = 1800
DEFAULT_AGENT_RUNTIME_INITIALIZE_TIMEOUT_SECONDS = 120
DEFAULT_AGENT_RUNTIME_BRIDGE_STARTUP_TIMEOUT_SECONDS = 30
Emit = Callable[[FactoryFrontendEvent], None]
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentPackageRunResult:
    package: LoadedAgentPackage
    final_state: Any
    session: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AgentPackageStreamRun:
    package: LoadedAgentPackage
    session: dict[str, Any]
    events: Iterator[tuple[str, Any]]


class AgentPackageRuntimeManager:
    def __init__(
        self,
        *,
        package_root: str | Path | None = None,
        system_package_root: str | Path | None = None,
        repository: AgentPackageRepository | None = None,
        launcher: DockerAgentRuntimeLauncher | None = None,
        emit: Emit | None = None,
    ) -> None:
        configured_root = package_root or os.getenv("AGENTFACTORY_PACKAGE_ROOT")
        configured_system_root = system_package_root or os.getenv("AGENTFACTORY_SYSTEM_PACKAGE_ROOT")
        self.repository = repository or AgentPackageRepository.from_paths(
            package_root=configured_root,
            system_package_root=configured_system_root,
        )
        self.launcher = launcher or DockerAgentRuntimeLauncher()
        self.workspace = AgentPackageWorkspaceService()
        self.extensions = AgentPackageExtensionService()
        self.idle_timeout_seconds = _env_int(
            "AGENTFACTORY_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS",
            DEFAULT_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS,
        )
        self.request_policy = RuntimeRequestPolicy.from_env()
        self.initialize_timeout_seconds = _env_int(
            "AGENTFACTORY_AGENT_RUNTIME_INITIALIZE_TIMEOUT_SECONDS",
            DEFAULT_AGENT_RUNTIME_INITIALIZE_TIMEOUT_SECONDS,
        )
        self.bridge_startup_timeout_seconds = _env_int(
            "AGENTFACTORY_AGENT_RUNTIME_BRIDGE_STARTUP_TIMEOUT_SECONDS",
            DEFAULT_AGENT_RUNTIME_BRIDGE_STARTUP_TIMEOUT_SECONDS,
        )
        self._containers: dict[str, AgentRuntimeContainerHandle] = {}
        self._system_handles: dict[str, SystemPackageRuntimeHandle] = {}
        self._instance_status_overrides: dict[str, dict[str, Any]] = {}
        self._mcp_gateways = HostMCPGatewayManager()
        self._skillhub_gateways = HostSkillHubGatewayManager()
        self._emit = emit
        self.resource_store = ResourceStore()
        self._resource_migration = self._migrate_package_resources()
        self._environment_migration = self._migrate_package_environments()

        # 容器池支持（可通过环境变量禁用）
        self._use_container_pool = _env_int("AGENTFACTORY_USE_CONTAINER_POOL", 1) == 1
        if self._use_container_pool:
            self._container_pool = get_global_container_pool()
        else:
            self._container_pool = None

    def set_emit(self, emit: Emit | None) -> None:
        self._emit = emit
        for handle in self._containers.values():
            handle.set_emit(emit)
        for handle in self._system_handles.values():
            handle.set_emit(emit)

    def emit_frontend_event(self, item: FactoryFrontendEvent) -> None:
        if self._emit is None:
            return
        self._emit(item)

    def emit_collaboration_session_updated(self, *, collaboration_id: str, session: dict[str, Any]) -> None:
        if self._emit is None:
            return
        self._emit(
            event(
                "debug_patch",
                request_id=None,
                mode="agent_package",
                graph_id="collaboration",
                producer_type="collaboration_service",
                payload={
                    "kind": "collaboration_session_updated",
                    "collaboration_id": collaboration_id,
                    "session": session,
                },
            )
        )

    def emit_factory_session_updated(self, *, session_record: Any, mode: str = "chat") -> None:
        if self._emit is None:
            return
        payload = session_payload(session_record, snapshot_mode=mode)
        self._emit(
            event(
                "session_switched",
                request_id=None,
                session_id=str(payload.get("session_id") or ""),
                mode=mode,
                producer_type="collaboration_service",
                payload={
                    "session_id": payload.get("session_id"),
                    "session": payload,
                    "force_restore": True,
                },
            )
        )

    def list_packages(self) -> list[dict[str, Any]]:
        packages = [
            self._package_summary(manifest_path)
            for manifest_path in self.repository.manifest_paths()
        ]
        return sorted(packages, key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    def resource_status(self, package_id: str) -> dict[str, Any]:
        package = self.load_package(package_id)
        contract = ResourcesContract.model_validate(package.contracts.get("resources") or {})
        return {
            "package_id": package_id,
            "key_available": self.resource_store.key_available,
            "resources": self.resource_store.status(package_id, contract.config.resource_descriptors),
            "migration": self._resource_migration.get(package_id, {"status": "complete", "migrated": False}),
        }

    def put_resource(self, package_id: str, resource_id: str, value: Any) -> dict[str, Any]:
        package = self.load_package(package_id)
        contract = ResourcesContract.model_validate(package.contracts.get("resources") or {})
        descriptors = {item.resource_id: item for item in contract.config.resource_descriptors}
        descriptor = descriptors.get(resource_id)
        if descriptor is None:
            raise ValueError(f"resource is not declared by package: {resource_id}")
        return self.resource_store.put(package_id, descriptor, value)

    def delete_resource(self, package_id: str, resource_id: str) -> dict[str, Any]:
        return {"package_id": package_id, "resource_id": resource_id, "deleted": self.resource_store.delete(package_id, resource_id)}

    def _migrate_package_resources(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        for manifest_path in self.repository.manifest_paths():
            try:
                results[manifest_path.parent.name] = migrate_package_resources(manifest_path.parent, store=self.resource_store)
            except Exception as exc:
                results[manifest_path.parent.name] = {"status": "pending", "reason": f"{type(exc).__name__}: {exc}"}
        return results

    def _migrate_package_environments(self) -> dict[str, dict[str, Any]]:
        results: dict[str, dict[str, Any]] = {}
        resolver = EnvironmentResolver()
        for manifest_path in self.repository.manifest_paths():
            package_id = manifest_path.parent.name
            if self._resource_migration.get(package_id, {}).get("status") != "complete":
                results[package_id] = {"status": "pending", "reason": "resource migration is pending"}
                continue
            try:
                lock = resolver.ensure(manifest_path.parent)
                results[package_id] = {"status": "complete", "image": lock.get("image")}
            except Exception as exc:
                results[package_id] = {"status": "pending", "reason": f"{type(exc).__name__}: {exc}"}
        return results

    def load_package(self, package_id: str) -> LoadedAgentPackage:
        return self.repository.load(package_id)

    def runtime_root_for_package(self, package_id: str) -> Path:
        return _host_runtime_root(package_id)

    def session_workdir_for_package(self, package_id: str, session_id: str) -> Path:
        return _host_session_workdir(package_id, session_id)

    def list_instance_statuses(self) -> list[dict[str, Any]]:
        package_ids = {item.get("package_id") for item in self.list_packages()}
        package_ids.update(handle.package_id for handle in self._containers.values())
        package_ids.update(handle.package_id for handle in self._system_handles.values())
        return [
            self.package_instance_status(str(package_id))
            for package_id in sorted(item for item in package_ids if item)
        ]

    def package_instance_status(self, package_id: str) -> dict[str, Any]:
        package = self.load_package(package_id)
        backend = "host" if _is_host_system_package(package) else "container"
        handles = self._runtime_handles_for_package(package_id, backend=backend)
        running = any(bool(getattr(handle, "is_running", False)) for handle in handles)
        active_request_count = sum(int(getattr(handle, "active_request_count", 0)) for handle in handles)
        active_command_types: set[str] = set()
        for handle in handles:
            active_command_types.update(str(item) for item in getattr(handle, "active_command_types", ()))
        base = {
            "package_id": package_id,
            "agent_id": package.assembly_spec.agent.id,
            "agent_name": package.assembly_spec.agent.name,
            "backend": backend,
            "status": "ready" if running else "stopped",
            "ready": running,
            "active_request_count": active_request_count,
            "runtime_root": str(_host_runtime_root(package_id)),
            "idle_timeout_seconds": self.idle_timeout_seconds,
        }
        if running and "initialize_runtime" in active_command_types:
            base.update({"status": "initializing", "ready": False})
        override = self._instance_status_overrides.get(package_id)
        if override:
            base.update(override)
            if not running and base.get("status") != "failed":
                base.update({"status": "stopped", "ready": False})
        return base

    def initialize_package(
        self,
        package_id: str,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        package = self.load_package(package_id)
        initializing_status = self._instance_status_payload(
            package_id=package_id,
            package=package,
            status="initializing",
            ready=False,
        )
        self._instance_status_overrides[package_id] = initializing_status
        if self._emit is not None:
            self._emit(
                event(
                    "agent_package_instance_updated",
                    request_id=request_id,
                    mode="agent_package",
                    graph_id="agent_package_runtime",
                    producer_type="factory_runtime",
                    payload=initializing_status,
                )
            )
        command = {
            "type": "initialize_runtime",
            "request_id": request_id or uuid4().hex,
            "payload": {
                "runtime_request": RuntimeRequestPolicy(
                    timeout_seconds=self.initialize_timeout_seconds,
                    heartbeat_seconds=self.request_policy.heartbeat_seconds,
                ).as_payload(),
            },
        }
        latest_status: dict[str, Any] | None = None
        try:
            for stream_mode, chunk in self._runtime_events(package_id, package=package, command=command):
                if stream_mode != "frontend_event":
                    continue
                item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
                if item.event_type == "agent_package_instance_updated":
                    latest_status = dict(item.payload or {})
                    self._instance_status_overrides[package_id] = latest_status
                elif item.event_type == "run_failed":
                    latest_status = self._instance_status_payload(
                        package_id=package_id,
                        package=package,
                        status="failed",
                        ready=False,
                        error=str(item.message or item.payload.get("message") or "initialize failed"),
                    )
                    self._instance_status_overrides[package_id] = latest_status
                    if self._emit is not None:
                        self._emit(
                            event(
                                "agent_package_instance_updated",
                                request_id=request_id,
                                mode="agent_package",
                                graph_id="agent_package_runtime",
                                producer_type="factory_runtime",
                                severity="error",
                                payload=latest_status,
                            )
                        )
                if self._emit is not None:
                    self._emit(item)
        except Exception as exc:
            latest_status = self._instance_status_payload(
                package_id=package_id,
                package=package,
                status="failed",
                ready=False,
                error=f"{type(exc).__name__}: {exc}",
            )
            self._instance_status_overrides[package_id] = latest_status
            if self._emit is not None:
                self._emit(
                    event(
                        "agent_package_instance_updated",
                        request_id=request_id,
                        mode="agent_package",
                        graph_id="agent_package_runtime",
                        producer_type="factory_runtime",
                        severity="error",
                        payload=latest_status,
                    )
                )
            raise
        return latest_status or self.package_instance_status(package_id)

    def shutdown_package_instance(
        self,
        package_id: str,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        self._close_package_containers(package_id)
        self._close_package_system_handles(package_id)
        status = self.package_instance_status(package_id)
        status = {**status, "status": "stopped", "ready": False}
        self._instance_status_overrides.pop(package_id, None)
        if self._emit is not None:
            self._emit(
                event(
                    "agent_package_instance_updated",
                    request_id=request_id,
                    mode="agent_package",
                    graph_id="agent_package_runtime",
                    producer_type="factory_runtime",
                    payload=status,
                )
            )
        return status

    def shutdown_session_runtime(
        self,
        package_id: str,
        *,
        session_id: str,
    ) -> bool:
        clean_session_id = str(session_id or "").strip()
        if not clean_session_id:
            return False
        package = self.load_package(package_id)
        runtime_key = f"{package_id}:session:{clean_session_id}"
        if _is_host_system_package(package):
            if runtime_key not in self._system_handles:
                return False
            self._close_system(runtime_key)
            return True
        if runtime_key not in self._containers:
            return False
        self._close_container(runtime_key)
        return True

    def scheduler_events(
        self,
        package_id: str,
        *,
        payload: dict[str, Any],
        request_id: str | None = None,
    ) -> Iterator[tuple[str, Any]]:
        package = self.load_package(package_id)
        command = {
            "type": "scheduler_manage",
            "request_id": request_id or uuid4().hex,
            "payload": dict(payload),
        }
        yield from self._runtime_events(package_id, package=package, command=command)

    def package_summary(self, package_id: str) -> dict[str, Any]:
        return self._package_summary(self._manifest_path(package_id))

    def update_context_config(
        self,
        package_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        package_dir = self.repository.package_dir(package_id)
        contract_path = package_dir / "contracts" / "context.json"
        if not contract_path.is_file():
            raise FileNotFoundError(f"context contract not found: {package_id}")
        document = _read_json_object(contract_path)
        config = document.setdefault("config", {})
        if not isinstance(config, dict):
            raise ValueError("context contract config must be an object")
        if "context_window_tokens" in payload:
            if payload["context_window_tokens"] is None:
                config.pop("context_window_tokens", None)
            else:
                config["context_window_tokens"] = payload["context_window_tokens"]
        if "compression_threshold_tokens" in payload:
            default_policy = config.setdefault("default_policy", {})
            if not isinstance(default_policy, dict):
                raise ValueError("context default_policy must be an object")
            compression = default_policy.setdefault("compression", {})
            if not isinstance(compression, dict):
                raise ValueError("context compression policy must be an object")
            if payload["compression_threshold_tokens"] is None:
                compression.pop("trigger_token_threshold", None)
            else:
                compression["trigger_token_threshold"] = payload["compression_threshold_tokens"]
        ContextContract.model_validate(document)
        contract_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return self.package_summary(package_id)

    def delete_package(self, package_id: str) -> dict[str, Any]:
        self._close_package_containers(package_id)
        self._close_package_system_handles(package_id)
        result = self.repository.delete_user_package(package_id)
        result["deleted_resource_count"] = self.resource_store.delete_package(package_id)
        result["agent_registry_refresh"] = _refresh_agent_registry_index(package_id)
        return result

    def export_package_archive(self, package_id: str) -> Path:
        return self.repository.export_user_package_archive(package_id)

    def list_sessions(self, package_id: str) -> list[dict[str, Any]]:
        package = self.load_package(package_id)
        return self._list_sessions_for_loaded_package(package)

    def list_recent_sessions(self, *, limit: int = 5) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for package in self.list_packages():
            package_id = str(package.get("package_id") or "").strip()
            if not package_id:
                continue
            package_name = str(package.get("agent_name") or package.get("name") or package_id)
            try:
                package_sessions = self.list_sessions(package_id)
            except Exception as exc:
                logger.warning("Failed to list sessions for package %s: %s", package_id, exc)
                continue
            for session in package_sessions:
                item = dict(session)
                item["package_id"] = package_id
                item["package_name"] = package_name
                item["agent_name"] = package_name
                sessions.append(item)
        sessions.sort(key=_session_updated_sort_key, reverse=True)
        return sessions[: max(1, limit)]

    def load_session(self, package_id: str, session_id: str) -> dict[str, Any]:
        package = self.load_package(package_id)
        session = self._session_manager_for_package(package_id, package).load(session_id).model_dump(mode="json")
        return _hydrate_session_runtime_view(session)

    def session_exists(self, package_id: str, session_id: str) -> bool:
        package = self.load_package(package_id)
        return self._session_manager_for_package(package_id, package).exists(session_id)

    def delete_session(self, package_id: str, session_id: str) -> dict[str, Any]:
        package = self.load_package(package_id)
        cancelled_active_request_count = self.cancel_active_requests(
            reason="session_deleted",
            package_id=package_id,
            session_id=session_id,
        )
        manager = self._session_manager_for_package(package_id, package)
        result = manager.delete_if_exists(session_id)
        if result is None:
            collaboration_unlink = CollaborationStore().unlink_runtime_session(
                package_id=package_id,
                session_id=session_id,
            )
            return {
                "package_id": package_id,
                "session_id": session_id,
                "deleted": False,
                "missing": True,
                "deleted_trace_count": 0,
                "deleted_checkpoint_count": 0,
                "collaboration_unlink": collaboration_unlink,
                "cancelled_active_request_count": cancelled_active_request_count,
                "sessions": self._list_sessions_for_loaded_package(package),
                "recent_agent_sessions": self.list_recent_sessions(),
            }
        deleted_checkpoint_count = _delete_agent_session_checkpoint(
            package_id=package_id,
            package=package,
            session_id=result.record.session_id,
            thread_id=result.record.thread_id,
        )
        deleted_workdir = _delete_session_workdir(package_id, result.record.session_id)
        collaboration_unlink = CollaborationStore().unlink_runtime_session(
            package_id=package_id,
            session_id=result.record.session_id,
        )
        return {
            "package_id": package_id,
            "session_id": result.record.session_id,
            "deleted": True,
            "deleted_trace_count": result.deleted_trace_count,
            "deleted_checkpoint_count": deleted_checkpoint_count,
            "deleted_workdir": deleted_workdir,
            "collaboration_unlink": collaboration_unlink,
            "cancelled_active_request_count": cancelled_active_request_count,
            "sessions": self._list_sessions_for_loaded_package(package),
            "recent_agent_sessions": self.list_recent_sessions(),
        }

    def workspace_roots(self, package_id: str, *, session_id: str | None = None) -> dict[str, Any]:
        package = self.load_package(package_id)
        return self.workspace.roots(package_id, package, session_id=session_id)

    def workspace_root_paths(self, package_id: str, *, session_id: str | None = None) -> dict[str, Path]:
        package = self.load_package(package_id)
        return workspace_roots(package_id, package, session_id=session_id)

    def list_workspace_entries(
        self,
        package_id: str,
        *,
        scope: str = "workdir",
        relative_path: str = "",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        package = self.load_package(package_id)
        return self.workspace.list_entries(
            package_id,
            package,
            scope=scope,
            relative_path=relative_path,
            session_id=session_id,
        )

    def read_workspace_file(
        self,
        package_id: str,
        *,
        scope: str = "workdir",
        relative_path: str,
        max_chars: int = 20000,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        package = self.load_package(package_id)
        return self.workspace.read_file(
            package_id,
            package,
            scope=scope,
            relative_path=relative_path,
            max_chars=max_chars,
            session_id=session_id,
        )

    def resolve_workspace_file(
        self,
        package_id: str,
        *,
        scope: str = "workdir",
        relative_path: str,
        session_id: str | None = None,
    ) -> Path:
        package = self.load_package(package_id)
        return self.workspace.resolve_file(
            package_id,
            package,
            scope=scope,
            relative_path=relative_path,
            session_id=session_id,
        )

    def extension_config_summary(self, package_id: str) -> dict[str, Any]:
        package = self.load_package(package_id)
        return self.extensions.summary(package_id, package)

    def system_extension_config_summary(self, resource_mode: str) -> dict[str, Any]:
        if resource_mode not in {"create_agent", "evolve_agent"}:
            raise ValueError(f"unsupported system extension resource mode: {resource_mode}")
        return self.extensions.system_summary(resource_mode)

    def extensions_manage(self, package_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        package = self.load_package(package_id)
        result = self.extensions.manage(package_id, package, action, payload)
        if result.changed:
            self._close_package_containers(package_id)
            self._close_package_system_handles(package_id)
        return result.payload

    def system_extensions_manage(self, resource_mode: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if resource_mode not in {"create_agent", "evolve_agent"}:
            raise ValueError(f"unsupported system extension resource mode: {resource_mode}")
        result = self.extensions.system_manage(resource_mode, action, payload)
        return result.payload

    def knowledge_runtime_for_package(self, package_id: str) -> KnowledgeRuntime:
        package = self.load_package(package_id)
        contract = package.contracts.get("knowledge") if isinstance(package.contracts, dict) else None
        config_payload = contract.get("config", {}) if isinstance(contract, dict) else {}
        config = KnowledgeContractConfig.model_validate(config_payload or {})
        runtime_root = _host_runtime_root(package_id)
        config = config.model_copy(
            update={
                "root": str(_runtime_contract_path(runtime_root, config.root)),
                "catalog_path": str(_runtime_contract_path(runtime_root, config.catalog_path)),
                "rag_store": config.rag_store.model_copy(
                    update={"path": str(_runtime_contract_path(runtime_root, config.rag_store.path))}
                ),
            },
            deep=True,
        )
        return build_knowledge_runtime(
            config=config,
            owner_type="agent",
            owner_id=package.assembly_spec.agent.id,
        ).runtime

    def knowledge_manage(self, package_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        runtime = self.knowledge_runtime_for_package(package_id)
        if action == "list_sources":
            return {"sources": [source.model_dump(mode="json") for source in runtime.list_sources()]}
        if action == "list_documents":
            return {
                "documents": [
                    document.model_dump(mode="json")
                    for document in runtime.list_documents(payload.get("source_id"))
                ]
            }
        if action == "search":
            results = runtime.search(
                query=str(payload.get("query") or ""),
                source_id=payload.get("source_id"),
                mode=str(payload.get("mode") or "auto"),
                top_k=int(payload.get("top_k") or 8),
            )
            return {"results": [result.model_dump(mode="json") for result in results]}
        if action == "open":
            return runtime.open(
                source_id=payload.get("source_id"),
                document_id=payload.get("document_id"),
                chunk_id=payload.get("chunk_id"),
            )
        if action == "read":
            return runtime.read(
                document_id=payload.get("document_id"),
                chunk_id=payload.get("chunk_id"),
                max_chars=payload.get("max_chars"),
            )
        if action == "prepare_source":
            source = _normalized_source_payload(payload.get("source") if isinstance(payload.get("source"), dict) else payload)
            preview = runtime.prepare_source(source)
            return {"preview": preview.model_dump(mode="json")}
        if action == "confirm_source":
            source = _normalized_source_payload(payload.get("source") if isinstance(payload.get("source"), dict) else payload)
            job = runtime.confirm_source(source)
            completed = runtime.run_job(job.job_id)
            return {"job": completed.model_dump(mode="json"), "sources": [item.model_dump(mode="json") for item in runtime.list_sources()]}
        if action == "remove_source":
            source_id = str(payload.get("source_id") or "")
            return {
                "source_id": source_id,
                "removed": runtime.remove_source(source_id),
                "sources": [item.model_dump(mode="json") for item in runtime.list_sources()],
            }
        if action == "reindex":
            source_id = str(payload.get("source_id") or "")
            job = runtime.reindex_source(source_id)
            completed = runtime.run_job(job.job_id)
            return {
                "source_id": source_id,
                "job": completed.model_dump(mode="json"),
                "sources": [item.model_dump(mode="json") for item in runtime.list_sources()],
            }
        raise ValueError(f"unsupported knowledge action: {action}")

    def ensure_session(
        self,
        package_id: str,
        *,
        session_id: str | None = None,
        first_user_input: str | None = None,
        session_kind: str = "normal",
        collaboration_id: str | None = None,
        collaboration_task_id: str | None = None,
        agent_group_id: str | None = None,
        visible_in_agent_session_list: bool | None = None,
    ) -> dict[str, Any]:
        package = self.load_package(package_id)
        manager = self._session_manager_for_package(package_id, package)
        if session_id:
            try:
                return manager.load(session_id).model_dump(mode="json")
            except FileNotFoundError:
                pass
        return manager.create(
            agent_id=package.assembly_spec.agent.id,
            first_user_input=first_user_input,
            session_kind=session_kind,
            collaboration_id=collaboration_id,
            collaboration_task_id=collaboration_task_id,
            agent_group_id=agent_group_id,
            visible_in_agent_session_list=visible_in_agent_session_list,
        ).model_dump(mode="json")

    def run(self, package_id: str, *, user_input: str, session_id: str | None = None) -> AgentPackageRunResult:
        raise RuntimeError("AgentPackage host-process execution is disabled; use stream() for sandbox execution.")

    def stream(
        self,
        package_id: str,
        *,
        user_input: str,
        display_user_input: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        user_config: dict[str, Any] | None = None,
        attachments: Any = None,
        message_metadata: dict[str, Any] | None = None,
        require_ready: bool = False,
        session_kind: str = "normal",
        collaboration_id: str | None = None,
        collaboration_task_id: str | None = None,
        agent_group_id: str | None = None,
        visible_in_agent_session_list: bool | None = None,
        workdir_root: Path | None = None,
    ) -> AgentPackageStreamRun:
        package = self.load_package(package_id)
        del require_ready
        resolved_request_id = request_id or uuid4().hex
        session_user_input = str(display_user_input or "").strip() or user_input
        session_manager = self._session_manager_for_package(package_id, package)
        if session_id:
            session = session_manager.load(session_id)
        else:
            session = session_manager.create(
                agent_id=package.assembly_spec.agent.id,
                first_user_input=session_user_input,
                session_kind=session_kind,
                collaboration_id=collaboration_id,
                collaboration_task_id=collaboration_task_id,
                agent_group_id=agent_group_id,
                visible_in_agent_session_list=visible_in_agent_session_list,
            )
        if session_id and (
            session_kind != "normal"
            or collaboration_id
            or collaboration_task_id
            or agent_group_id
            or visible_in_agent_session_list is not None
        ):
            session = session_manager.update_metadata(
                session.session_id,
                session_kind=session_kind,
                collaboration_id=collaboration_id,
                collaboration_task_id=collaboration_task_id,
                agent_group_id=agent_group_id,
                visible_in_agent_session_list=visible_in_agent_session_list,
            )
        resolved_workdir_root = workdir_root or self.session_workdir_for_package(package_id, session.session_id)
        attachment_result = self._prepare_runtime_attachments(
            package_id=package_id,
            package=package,
            workdir_root=resolved_workdir_root,
            user_input=user_input,
            attachments=attachments,
        )
        session = session_manager.touch_turn(
            session.session_id,
            request_id=resolved_request_id,
            first_user_input=session_user_input,
            user_input=session_user_input,
            attachments=attachment_result.attachments,
            message_metadata=message_metadata,
            status="running",
        )
        command = {
            "type": "run_message",
            "request_id": resolved_request_id,
            "payload": {
                "message": attachment_result.message,
                "session_id": session.session_id,
                "user_config": dict(user_config or {}),
                "attachments": attachment_result.attachments,
                "runtime_request": self.request_policy.as_payload(),
            },
        }
        if _is_host_system_package(package):
            return AgentPackageStreamRun(
                package=package,
                session=session.model_dump(mode="json"),
                events=self._system_events(package_id, package=package, command=command, workdir_root=resolved_workdir_root),
            )
        return AgentPackageStreamRun(
            package=package,
            session=session.model_dump(mode="json"),
            events=self._container_events(package_id, package=package, command=command, workdir_root=resolved_workdir_root),
        )

    def _prepare_runtime_attachments(
        self,
        *,
        package_id: str,
        package: LoadedAgentPackage,
        workdir_root: Path,
        user_input: str,
        attachments: Any,
    ) -> AttachmentImportResult:
        attachment_scope = time_named_attachment_scope()
        if _is_host_system_package(package):
            runtime_workdir = str(workdir_root)
        else:
            try:
                runtime_workdir = str(runtime_container_path(workdir_root))
            except ValueError:
                runtime_workdir = "/workdir"
        runtime_path_root = str(PurePosixPath(runtime_workdir) / ATTACHMENT_INPUT_DIR / attachment_scope)
        return import_runtime_attachments(
            user_input,
            attachments,
            storage_root=workdir_root / ATTACHMENT_INPUT_DIR / attachment_scope,
            runtime_path_root=runtime_path_root,
            base_dir=project_root(),
            scope=attachment_scope,
        )

    def resume_stream(
        self,
        package_id: str,
        *,
        session_id: str,
        resume_payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        workdir_root: Path | None = None,
    ) -> AgentPackageStreamRun:
        package = self.load_package(package_id)
        session = self._session_manager_for_package(package_id, package).load(session_id)
        resolved_workdir_root = workdir_root or self.session_workdir_for_package(package_id, session.session_id)
        command = {
            "type": "resume_interrupt",
            "request_id": request_id or uuid4().hex,
            "payload": {
                "session_id": session_id,
                "resume_payload": resume_payload or {},
                "runtime_request": self.request_policy.as_payload(),
            },
        }

        if _is_host_system_package(package):
            return AgentPackageStreamRun(
                package=package,
                session=session.model_dump(mode="json"),
                events=self._system_events(package_id, package=package, command=command, workdir_root=resolved_workdir_root),
            )
        return AgentPackageStreamRun(
            package=package,
            session=session.model_dump(mode="json"),
            events=self._container_events(package_id, package=package, command=command, workdir_root=resolved_workdir_root),
        )

    def finish_session_turn(
        self,
        package_id: str,
        *,
        session_id: str,
        request_id: str | None = None,
        final_answer: str | None,
        reasoning_content: str | None = None,
        status: str,
        tool_activities: list[dict[str, Any]] | None = None,
        trace_ref: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        package = self.load_package(package_id)
        session = self._session_manager_for_package(package_id, package).finish_turn(
            session_id,
            request_id=request_id,
            final_answer=final_answer,
            reasoning_content=reasoning_content,
            status=status,
            tool_activities=tool_activities,
            trace_ref=trace_ref,
        )
        return session.model_dump(mode="json")

    def _package_summary(self, manifest_path: Path) -> dict[str, Any]:
        package_id = manifest_path.parent.name
        try:
            package = self.repository.load_manifest(manifest_path)
            report = _read_json_object(manifest_path.parent / "package_report.json")
            sessions = self._list_sessions_for_loaded_package(package)
            detail = _package_detail_summary(self, package_id=package_id, package=package)
            return {
                "package_id": package_id,
                "package_path": str(manifest_path.parent),
                "manifest_path": str(manifest_path),
                "factory_run_id": package.manifest.factory_run_id,
                "agent_id": package.assembly_spec.agent.id,
                "agent_name": package.assembly_spec.agent.name,
                "agent_description": package.assembly_spec.agent.description,
                "status": str(report.get("status") or "available"),
                "updated_at": _path_updated_at(manifest_path.parent),
                "tool_count": len(package.assembly_spec.tools),
                "session_count": len(sessions),
                "model_contract": _model_contract_summary(package),
                "context_contract": _context_contract_summary(manifest_path.parent),
                "resources": self.resource_status(package_id),
                "environment": {**_environment_summary(manifest_path.parent), "migration": self._environment_migration.get(package_id)},
                "extensions": _extensions_summary(package_id, package=package),
                **detail,
            }
        except Exception as exc:
            return {
                "package_id": package_id,
                "package_path": str(manifest_path.parent),
                "manifest_path": str(manifest_path),
                "status": "invalid",
                "updated_at": _path_updated_at(manifest_path.parent),
                "error": f"{type(exc).__name__}: {exc}",
                "model_contract": {"version": "", "bindings": {}, "tool_bindings": {}},
                "context_contract": _context_contract_summary(manifest_path.parent),
                "extensions": _extensions_summary(package_id),
                "tools": [],
                "mcp_servers": [],
                "skills": [],
                "knowledge_sources": [],
            }

    def _session_manager_for_package(self, package_id: str, package: LoadedAgentPackage) -> AgentSessionManager:
        session_contract = package.contracts.get("session") if isinstance(package.contracts, dict) else None
        config = session_contract.get("config", {}) if isinstance(session_contract, dict) else {}
        root = _host_runtime_root(package_id) / "sessions"
        if isinstance(config, dict):
            configured = str(config.get("session_root") or "")
            if configured:
                root = _host_session_root(package_id=package_id, package=package, configured=configured)
        return AgentSessionManager(AgentSessionConfig(root=root))

    def _list_sessions_for_loaded_package(self, package: LoadedAgentPackage) -> list[dict[str, Any]]:
        manager = self._session_manager_for_package(package.package_root.name, package)
        return [
            record.model_dump(mode="json")
            for record in manager.list_sessions(agent_id=package.assembly_spec.agent.id)
        ]

    def close_all(self) -> None:
        for runtime_key in list(self._containers):
            self._close_container(runtime_key)
        for runtime_key in list(self._system_handles):
            self._close_system(runtime_key)
        self._mcp_gateways.close_all()
        self._skillhub_gateways.close_all()
        if self._use_container_pool:
            shutdown_global_container_pool()
        shutdown_shared_runtime()

    def cancel_active_requests(
        self,
        *,
        reason: str = "user_cancelled",
        request_id: str | None = None,
        package_id: str | None = None,
        session_id: str | None = None,
        visible_output: Any = None,
    ) -> int:
        cancelled = 0
        target_package_id = str(package_id or "").strip()
        container_items = [
            (key, handle)
            for key, handle in self._containers.items()
            if not target_package_id or handle.package_id == target_package_id
        ]
        system_items = [
            (key, handle)
            for key, handle in self._system_handles.items()
            if not target_package_id or handle.package_id == target_package_id
        ]
        for _, handle in container_items:
            cancelled += handle.cancel_active_requests(
                reason=reason,
                request_id=request_id,
                session_id=session_id,
                visible_output=visible_output,
            )
        for _, handle in system_items:
            cancelled += handle.cancel_active_requests(
                reason=reason,
                request_id=request_id,
                session_id=session_id,
                visible_output=visible_output,
            )
        return cancelled

    def _system_events(
        self,
        package_id: str,
        *,
        package: LoadedAgentPackage,
        command: dict[str, Any],
        workdir_root: Path | None = None,
    ) -> Iterator[tuple[str, Any]]:
        request_id = str(command.get("request_id") or uuid4().hex)
        command["request_id"] = request_id
        runtime_key = _runtime_handle_key(package_id, command)
        will_start = not self._has_reusable_system_handle(runtime_key, package)
        if will_start:
            yield "frontend_event", node_event(
                request_id,
                "node_started",
                node_id="runtime_container",
                payload={"package_id": package_id, "backend": "host", "status": "preflight"},
            )
        try:
            handle = self._system_handle(
                package_id,
                package,
                runtime_key=runtime_key,
                workdir_root=workdir_root,
            )
            if handle.startup_payload is not None:
                yield "frontend_event", node_event(
                    request_id,
                    "node_completed",
                    node_id="runtime_container",
                    payload=handle.startup_payload,
                )
                handle.startup_payload = None
        except Exception as exc:
            failure_payload = {
                "where": "system_package.launch",
                "why": "host_runtime_start_failed",
                "message": f"{type(exc).__name__}: {exc}",
                "suggested_action": "Check the SystemPackage manifest, contracts, and runtime paths.",
            }
            if will_start:
                yield "frontend_event", node_event(
                    request_id,
                    "node_failed",
                    node_id="runtime_container",
                    payload=failure_payload,
                    severity="error",
                )
            yield "frontend_event", run_failed_event(request_id, failure_payload)
            return
        yield from _scoped_runtime_events(handle.send(command), package_id=package_id)

    def _container_events(
        self,
        package_id: str,
        *,
        package: LoadedAgentPackage,
        command: dict[str, Any],
        workdir_root: Path | None = None,
    ) -> Iterator[tuple[str, Any]]:
        request_id = str(command.get("request_id") or uuid4().hex)
        command["request_id"] = request_id
        runtime_key = _runtime_handle_key(package_id, command)
        will_start = not self._has_reusable_container(runtime_key, package)
        if will_start:
            yield "frontend_event", node_event(
                request_id,
                "node_started",
                node_id="runtime_container",
                payload={"package_id": package_id, "status": "preflight"},
            )
        try:
            handle = self._container(
                package_id,
                package,
                runtime_key=runtime_key,
                workdir_root=workdir_root,
            )
            if handle.startup_payload is not None:
                yield "frontend_event", node_event(
                    request_id,
                    "node_completed",
                    node_id="runtime_container",
                    payload=handle.startup_payload,
                )
                handle.startup_payload = None
        except AgentRuntimeLaunchError as exc:
            if will_start:
                yield "frontend_event", node_event(
                    request_id,
                    "node_failed",
                    node_id="runtime_container",
                    payload=exc.payload,
                    severity="error",
                )
            yield "frontend_event", run_failed_event(request_id, exc.payload)
            return
        except Exception as exc:
            failure_payload = {
                "where": "agent_runtime.launch",
                "why": "container_start_failed",
                "message": f"{type(exc).__name__}: {exc}",
                "suggested_action": "Check Docker Desktop, runtime image, and sandbox contract.",
            }
            if will_start:
                yield "frontend_event", node_event(
                    request_id,
                    "node_failed",
                    node_id="runtime_container",
                    payload=failure_payload,
                    severity="error",
                )
            yield "frontend_event", run_failed_event(
                request_id,
                failure_payload,
            )
            return
        try:
            yield from _scoped_runtime_events(handle.send(command), package_id=package_id)
        except Exception:
            self._close_container(runtime_key)
            raise

    def _runtime_events(
        self,
        package_id: str,
        *,
        package: LoadedAgentPackage,
        command: dict[str, Any],
    ) -> Iterator[tuple[str, Any]]:
        if _is_host_system_package(package):
            yield from self._system_events(package_id, package=package, command=command)
            return
        yield from self._container_events(package_id, package=package, command=command)

    def _instance_status_payload(
        self,
        *,
        package_id: str,
        package: LoadedAgentPackage,
        status: str,
        ready: bool,
        error: str | None = None,
    ) -> dict[str, Any]:
        backend = "host" if _is_host_system_package(package) else "container"
        payload: dict[str, Any] = {
            "package_id": package_id,
            "agent_id": package.assembly_spec.agent.id,
            "agent_name": package.assembly_spec.agent.name,
            "backend": backend,
            "status": status,
            "ready": ready,
            "runtime_root": str(_host_runtime_root(package_id)),
            "idle_timeout_seconds": self.idle_timeout_seconds,
        }
        if error:
            payload["error"] = error
        return payload

    def _container(
        self,
        package_id: str,
        package: LoadedAgentPackage,
        *,
        runtime_key: str,
        workdir_root: Path | None = None,
    ) -> "AgentRuntimeContainerHandle":
        fingerprint = _runtime_fingerprint(package_id, package)

        # 如果启用容器池，优先从池中获取
        if self._use_container_pool and self._container_pool is not None and workdir_root is None:
            # 检查当前 runtime_key 是否已有活跃容器
            existing = self._containers.get(runtime_key)
            if (
                existing is not None
                and existing.is_running
                and existing.package_fingerprint == fingerprint
            ):
                return existing

            if existing is not None:
                self._close_container(runtime_key)

            # 从池中获取或创建容器
            def create_container_for_pool():
                return self._create_container_handle(
                    package_id,
                    package,
                    fingerprint,
                    runtime_key,
                    workdir_root,
                )

            try:
                handle = self._container_pool.acquire(
                    package_id=package_id,
                    package_fingerprint=fingerprint,
                    runtime_instance_id=runtime_key,
                    create_fn=create_container_for_pool,
                )
                # 将容器关联到当前 runtime_key
                self._containers[runtime_key] = handle
                return handle
            except Exception:
                # 池获取失败，回退到传统方式
                pass

        # 传统方式：每个 session 独立容器
        existing = self._containers.get(runtime_key)
        if (
            existing is not None
            and existing.is_running
            and existing.package_fingerprint == fingerprint
            and not existing.is_idle(self.idle_timeout_seconds)
        ):
            return existing

        self._close_container(runtime_key)
        handle = self._create_container_handle(
            package_id,
            package,
            fingerprint,
            runtime_key,
            workdir_root,
        )
        self._containers[runtime_key] = handle
        return handle

    def _create_container_handle(
        self,
        package_id: str,
        package: LoadedAgentPackage,
        fingerprint: str,
        runtime_instance_id: str,
        workdir_root: Path | None,
    ) -> "AgentRuntimeContainerHandle":
        """创建新的容器 handle（提取为独立方法供池使用）"""
        runtime_root = _host_runtime_root(package_id)
        artifacts_root = runtime_root / "artifacts" / uuid4().hex
        workdir_root = workdir_root or _host_scratch_workdir(package_id)
        extension_root = _extension_root_for_package(package_id, package)
        for path in (artifacts_root, workdir_root, runtime_root, extension_root):
            path.mkdir(parents=True, exist_ok=True)
        mcp_gateway = self._mcp_gateways.ensure_gateway(
            _load_extension_bundle(extension_root, package=package).mcp_servers
        )
        skillhub_gateway = self._skillhub_gateways.ensure_gateway(extension_root)
        plan = self.launcher.prepare(
            package=package,
            runtime_root=runtime_root,
            artifacts_root=artifacts_root,
            workdir_root=workdir_root,
            runtime_instance_id=runtime_instance_id,
            extension_root=extension_root,
            mcp_gateway_url=mcp_gateway.docker_url if mcp_gateway is not None else None,
            skillhub_gateway_url=skillhub_gateway.docker_url,
        )
        handle = AgentRuntimeContainerHandle(
            package_id=package_id,
            package_fingerprint=fingerprint,
            idle_timeout_seconds=self.idle_timeout_seconds,
            request_policy=self.request_policy,
            bridge_startup_timeout_seconds=self.bridge_startup_timeout_seconds,
            command=plan.command,
            emit=self._emit,
        )
        handle.startup_payload = {
            "package_id": package_id,
            "status": "running",
            "pid": handle.process.pid,
            "image": plan.image,
            "network": plan.network,
            "mount_count": plan.mount_count,
            "extension_root": str(plan.extension_root),
            "preflight": plan.preflight,
            "isolation": plan.isolation,
            "shared_container_id": plan.shared_container_id,
        }
        return handle

    def _system_handle(
        self,
        package_id: str,
        package: LoadedAgentPackage,
        *,
        runtime_key: str,
        workdir_root: Path | None = None,
    ) -> "SystemPackageRuntimeHandle":
        existing = self._system_handles.get(runtime_key)
        fingerprint = _runtime_fingerprint(package_id, package)
        if (
            existing is not None
            and existing.package_fingerprint == fingerprint
            and not existing.is_idle(self.idle_timeout_seconds)
        ):
            return existing
        self._close_system(runtime_key)
        runtime_root = _host_runtime_root(package_id)
        artifacts_root = runtime_root / "artifacts"
        workdir_root = workdir_root or _host_scratch_workdir(package_id)
        extension_root = _extension_root_for_package(package_id, package)
        for path in (artifacts_root, workdir_root, runtime_root, extension_root):
            path.mkdir(parents=True, exist_ok=True)
        host_package = host_runtime_package_view(
            package,
            runtime_root=runtime_root,
            artifacts_root=artifacts_root,
            workdir_root=workdir_root,
            extension_root=extension_root,
        )
        handle = SystemPackageRuntimeHandle(
            package_id=package_id,
            package=host_package,
            package_fingerprint=fingerprint,
            runtime_root=runtime_root,
            runtime_instance_id=runtime_key,
            instance_extension_root=extension_root,
            idle_timeout_seconds=self.idle_timeout_seconds,
            request_policy=self.request_policy,
            producer_type="factory_runtime" if _is_system_package(package) else "agent_runtime_host",
            emit=self._emit,
        )
        handle.startup_payload = {
            "status": "running",
            "backend": "host",
            "package_id": package_id,
            "runtime_root": str(runtime_root),
            "artifact_root": str(artifacts_root),
            "workdir": str(workdir_root),
            "extension_root": str(extension_root),
        }
        self._system_handles[runtime_key] = handle
        return handle

    def _has_reusable_container(self, runtime_key: str, package: LoadedAgentPackage) -> bool:
        existing = self._containers.get(runtime_key)
        if existing is None or not existing.is_running:
            return False
        if existing.package_fingerprint != _runtime_fingerprint(existing.package_id, package):
            return False
        return not existing.is_idle(self.idle_timeout_seconds)

    def _has_reusable_system_handle(self, runtime_key: str, package: LoadedAgentPackage) -> bool:
        existing = self._system_handles.get(runtime_key)
        if existing is None or not existing.is_running:
            return False
        if existing.package_fingerprint != _runtime_fingerprint(existing.package_id, package):
            return False
        return not existing.is_idle(self.idle_timeout_seconds)

    def _has_ready_runtime(self, package_id: str, package: LoadedAgentPackage) -> bool:
        if _is_host_system_package(package):
            return any(
                self._has_reusable_system_handle(key, package)
                for key, handle in self._system_handles.items()
                if handle.package_id == package_id
            )
        return any(
            self._has_reusable_container(key, package)
            for key, handle in self._containers.items()
            if handle.package_id == package_id
        )

    def _close_container(self, runtime_key: str) -> None:
        handle = self._containers.pop(runtime_key, None)
        package_id = handle.package_id if handle is not None else _runtime_key_package_id(runtime_key)
        self._instance_status_overrides.pop(package_id, None)
        if handle is not None:
            # 如果启用容器池，释放回池而不是直接关闭
            if self._use_container_pool and self._container_pool is not None:
                self._container_pool.release(handle)
            else:
                handle.close()

    def _close_system(self, runtime_key: str) -> None:
        handle = self._system_handles.pop(runtime_key, None)
        package_id = handle.package_id if handle is not None else _runtime_key_package_id(runtime_key)
        self._instance_status_overrides.pop(package_id, None)
        if handle is not None:
            handle.close()

    def _close_package_containers(self, package_id: str) -> None:
        for runtime_key, handle in list(self._containers.items()):
            if handle.package_id == package_id:
                self._close_container(runtime_key)

    def _close_package_system_handles(self, package_id: str) -> None:
        for runtime_key, handle in list(self._system_handles.items()):
            if handle.package_id == package_id:
                self._close_system(runtime_key)

    def _runtime_handles_for_package(self, package_id: str, *, backend: str) -> list[Any]:
        handles = self._system_handles if backend == "host" else self._containers
        return [handle for handle in handles.values() if handle.package_id == package_id]

    def _manifest_path(self, package_id: str) -> Path:
        return self.repository.manifest_path(package_id)

    def _package_dir(self, package_id: str, *, include_system_packages: bool = True) -> Path:
        return self.repository.package_dir(package_id, include_system_packages=include_system_packages)

def _scoped_runtime_events(
    events: Iterator[tuple[str, Any]],
    *,
    package_id: str,
) -> Iterator[tuple[str, Any]]:
    for stream_mode, chunk in events:
        if stream_mode == "frontend_event":
            yield stream_mode, _scoped_runtime_event(chunk, package_id=package_id)
            continue
        yield stream_mode, chunk


def _scoped_runtime_event(chunk: Any, *, package_id: str) -> FactoryFrontendEvent:
    item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
    payload = item.payload if isinstance(item.payload, dict) else None
    if payload is None:
        return item
    return item.model_copy(update={"payload": {**payload, "package_id": package_id}})


def _runtime_handle_key(package_id: str, command: dict[str, Any]) -> str:
    payload = command.get("payload") if isinstance(command.get("payload"), dict) else {}
    session_id = str(payload.get("session_id") or "").strip()
    return f"{package_id}:session:{session_id}" if session_id else f"{package_id}:package"


def _runtime_key_package_id(runtime_key: str) -> str:
    return runtime_key.split(":", 1)[0]


def _delete_session_workdir(package_id: str, session_id: str) -> bool:
    workdir = _host_session_workdir(package_id, session_id)
    if not workdir.exists():
        return False
    shutil.rmtree(workdir)
    return True


def _package_fingerprint(package: LoadedAgentPackage) -> str:
    digest = hashlib.sha256()
    digest.update(str(package.package_root.resolve()).encode("utf-8"))
    _hash_tree(digest, package.package_root)
    if _is_system_package(package):
        extension_root = _extension_root_for_package(package.package_root.name, package)
        if extension_root.resolve() != package.package_root.resolve():
            _hash_tree(digest, extension_root)
    if _is_host_system_package(package):
        digest.update(b"host-system-package")
    else:
        lock = EnvironmentResolver().read_lock(package.package_root)
        digest.update(str(lock.get("image_digest") or lock.get("image") or "").encode("utf-8"))
    return digest.hexdigest()


def _runtime_fingerprint(package_id: str, package: LoadedAgentPackage) -> str:
    digest = hashlib.sha256()
    digest.update(_package_fingerprint(package).encode("utf-8"))
    extension_root = _extension_root_for_package(package_id, package)
    digest.update(b"runtime-extension-root")
    digest.update(str(extension_root.resolve()).encode("utf-8"))
    _hash_tree(digest, extension_root)
    return digest.hexdigest()


def _environment_summary(package_root: Path) -> dict[str, Any]:
    try:
        lock = EnvironmentResolver().read_lock(package_root)
        pool = lock.get("pool") if isinstance(lock.get("pool"), dict) else {}
        return {
            "status": lock.get("status"),
            "image": lock.get("image"),
            "image_digest": lock.get("image_digest"),
            "platform": lock.get("platform"),
            "dependency_pool": {
                "python_entry_count": len(pool.get("python_entries") or []),
                "system_entry_count": len(pool.get("system_entries") or []),
                "has_npm_profile": bool(pool.get("npm_profile")),
            },
            "verified_at": lock.get("verified_at"),
        }
    except Exception as exc:
        return {"status": "missing", "error": f"{type(exc).__name__}: {exc}"}


def _hash_tree(digest: "hashlib._Hash", root: Path) -> None:
    if not root.exists():
        digest.update(f"missing:{root}".encode("utf-8"))
        return
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            stat = path.stat()
        except OSError:
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            relative = path
        digest.update(str(relative).encode("utf-8"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
        digest.update(str(stat.st_size).encode("ascii"))


def _runtime_image_identity() -> str:
    image = DEFAULT_RUNTIME_IMAGE
    docker = shutil.which("docker")
    if docker is None:
        return f"image:{image}"
    try:
        result = subprocess.run(
            [docker, "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return f"image:{image}"
    identity = result.stdout.strip() if result.returncode == 0 else image
    return f"image:{image}:{identity}"


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _delete_agent_session_checkpoint(
    *,
    package_id: str,
    package: LoadedAgentPackage,
    session_id: str,
    thread_id: str,
) -> int:
    session_contract = package.contracts.get("session") if isinstance(package.contracts, dict) else None
    config = session_contract.get("config", {}) if isinstance(session_contract, dict) else {}
    backend = str(config.get("checkpointer_backend") or "sqlite").strip().lower()
    if backend != "sqlite":
        return 0
    checkpoint_path = str(config.get("checkpoint_path") or ".agent_runtime/checkpoints/agent.sqlite").strip()
    path = _runtime_contract_path(_host_runtime_root(package_id), checkpoint_path)
    path = instance_checkpoint_path(path, f"{package_id}:session:{session_id}")
    return 1 if delete_sqlite_checkpoint_thread(path, thread_id) else 0


def _model_contract_summary(package: LoadedAgentPackage) -> dict[str, Any]:
    contract = package.contracts.get("model") if isinstance(package.contracts, dict) else None
    if not isinstance(contract, dict):
        return {"version": "", "bindings": {}, "tool_bindings": {}}
    config = contract.get("config") if isinstance(contract.get("config"), dict) else {}
    bindings = config.get("bindings") if isinstance(config.get("bindings"), dict) else {}
    tool_bindings = config.get("tool_bindings") if isinstance(config.get("tool_bindings"), dict) else {}
    public_bindings: dict[str, dict[str, Any]] = {}
    for role, binding in bindings.items():
        if not isinstance(binding, dict):
            continue
        public_bindings[str(role)] = {
            "profile_id": str(binding.get("profile_id") or ""),
            "source": str(binding.get("source") or "model_pool"),
            "selection_source": str(binding.get("selection_source") or ""),
            "reason": str(binding.get("reason") or ""),
            "required_capabilities": binding.get("required_capabilities") if isinstance(binding.get("required_capabilities"), dict) else {},
            "overrides": binding.get("overrides") if isinstance(binding.get("overrides"), dict) else {},
        }
    public_tool_bindings: dict[str, dict[str, Any]] = {}
    for tool_id, binding in tool_bindings.items():
        if not isinstance(binding, dict):
            continue
        public_tool_bindings[str(tool_id)] = {
            "profile_id": str(binding.get("profile_id") or ""),
            "source": str(binding.get("source") or "model_pool"),
            "capability": str(binding.get("capability") or ""),
            "selection_source": str(binding.get("selection_source") or ""),
            "reason": str(binding.get("reason") or ""),
            "description": str(binding.get("description") or ""),
            "required_capabilities": binding.get("required_capabilities") if isinstance(binding.get("required_capabilities"), dict) else {},
            "overrides": binding.get("overrides") if isinstance(binding.get("overrides"), dict) else {},
        }
    return {
        "version": str(contract.get("version") or ""),
        "bindings": public_bindings,
        "tool_bindings": public_tool_bindings,
    }


def _context_contract_summary(package_root: Path) -> dict[str, Any]:
    contract_path = package_root / "contracts" / "context.json"
    env_context_window = context_window_tokens_from_env()
    env_compression_threshold = _compression_threshold_from_env()
    env_effective_compression_threshold = (
        min(env_compression_threshold, env_context_window)
        if isinstance(env_context_window, int) and env_context_window > 0
        else env_compression_threshold
    )
    base = {
        "version": "",
        "context_window_tokens": None,
        "context_window_tokens_source": "env" if env_context_window is not None else "unset",
        "context_window_tokens_env": env_context_window,
        "context_window_tokens_custom": None,
        "compression_threshold_tokens": env_effective_compression_threshold,
        "compression_threshold_tokens_source": "env",
        "compression_threshold_tokens_env": env_compression_threshold,
        "compression_threshold_tokens_custom": None,
    }
    if not contract_path.is_file():
        return base
    try:
        document = _read_json_object(contract_path)
        validated = ContextContract.model_validate(document)
    except Exception as exc:
        return {**base, "error": f"{type(exc).__name__}: {exc}"}
    config = document.get("config") if isinstance(document.get("config"), dict) else {}
    custom_window = config.get("context_window_tokens")
    window = custom_window if isinstance(custom_window, int) and custom_window > 0 else env_context_window
    compression = {}
    default_policy = config.get("default_policy") if isinstance(config.get("default_policy"), dict) else {}
    if isinstance(default_policy, dict):
        compression = default_policy.get("compression") if isinstance(default_policy.get("compression"), dict) else {}
    custom_threshold = compression.get("trigger_token_threshold") if isinstance(compression, dict) else None
    threshold = custom_threshold if isinstance(custom_threshold, int) and custom_threshold > 0 else env_compression_threshold
    effective_threshold = min(threshold, window) if isinstance(window, int) and window > 0 else threshold
    return {
        **base,
        "version": validated.version,
        "context_window_tokens": window,
        "context_window_tokens_source": "package" if isinstance(custom_window, int) and custom_window > 0 else base["context_window_tokens_source"],
        "context_window_tokens_custom": custom_window if isinstance(custom_window, int) and custom_window > 0 else None,
        "compression_threshold_tokens": effective_threshold,
        "compression_threshold_tokens_source": "package" if isinstance(custom_threshold, int) and custom_threshold > 0 else "env",
        "compression_threshold_tokens_custom": custom_threshold if isinstance(custom_threshold, int) and custom_threshold > 0 else None,
    }


def _hydrate_session_runtime_view(session: dict[str, Any]) -> dict[str, Any]:
    hydrated = dict(session)
    trace_records = _session_trace_records(hydrated)
    if not trace_records:
        return hydrated
    latest_context = _latest_trace_event_payload(trace_records, "context_window_updated")
    if latest_context:
        hydrated["context_window"] = latest_context
    latest_plan = _latest_trace_event_payload(trace_records, "plan_updated")
    if latest_plan:
        hydrated["current_plan"] = latest_plan
    return hydrated


def _refresh_agent_registry_index(package_id: str) -> dict[str, Any]:
    try:
        return refresh_agent_registry_index(package_id)
    except Exception as exc:
        return {"status": "failed", "message": f"{type(exc).__name__}: {exc}"}


def _session_trace_records(session: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    runtime_refs = session.get("runtime_refs") if isinstance(session.get("runtime_refs"), dict) else {}
    default_trace_root = _trace_root_from_ref(runtime_refs)
    turns = session.get("turns") if isinstance(session.get("turns"), list) else []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        trace_ref = turn.get("trace_ref") if isinstance(turn.get("trace_ref"), dict) else {}
        trace_id = str(trace_ref.get("trace_id") or "").strip()
        if not trace_id or not _safe_path_id(trace_id):
            continue
        trace_root = _trace_root_from_ref(trace_ref) or default_trace_root
        if trace_root is None:
            continue
        records.extend(_read_trace_jsonl(trace_root / "runs" / trace_id / "trace.jsonl"))
    return records


def _latest_trace_event_payload(records: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for record in reversed(records):
        if record.get("event_type") != event_type:
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        return {
            **payload,
            "updated_at": record.get("created_at"),
            "trace_id": record.get("trace_id"),
            "run_id": record.get("run_id"),
        }
    return None


def _read_trace_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def _trace_root_from_ref(ref: dict[str, Any]) -> Path | None:
    value = str(ref.get("trace_root") or ref.get("trace") or "").strip()
    if not value:
        return None
    return Path(value).expanduser()


def _safe_path_id(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in {"-", "_"} for char in value)


def _compression_threshold_from_env() -> int:
    value = os.getenv(MODEL_COMPRESSION_TRIGGER_TOKENS_ENV)
    if value:
        try:
            parsed = int(value)
        except ValueError:
            parsed = 0
        if parsed >= 1000:
            return parsed
    return DEFAULT_COMPRESSION_TRIGGER_TOKEN_THRESHOLD


def _package_detail_summary(
    manager: AgentPackageRuntimeManager,
    *,
    package_id: str,
    package: LoadedAgentPackage,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "tools": [_public_package_tool(spec) for spec in package.assembly_spec.tools],
        "mcp_servers": [],
        "skills": [],
        "knowledge_sources": [],
    }
    detail.update(_package_extension_detail(package_id=package_id, package=package))
    detail.update(_package_knowledge_detail(manager, package_id=package_id))
    return detail


def _package_knowledge_detail(manager: AgentPackageRuntimeManager, *, package_id: str) -> dict[str, Any]:
    try:
        runtime = manager.knowledge_runtime_for_package(package_id)
        sources = runtime.list_sources()
        document_counts = {
            source.source_id: len(runtime.list_documents(source.source_id))
            for source in sources
        }
        return {
            "knowledge_sources": [
                _public_knowledge_source(
                    source.model_dump(mode="json"),
                    document_count=document_counts.get(source.source_id),
                )
                for source in sources
            ],
        }
    except Exception as exc:
        return {
            "knowledge_sources": [],
            "knowledge_error": f"{type(exc).__name__}: {exc}",
        }


def _public_package_tool(spec: Any) -> dict[str, Any]:
    return {
        "kind": "package_tool",
        "id": str(getattr(spec, "id", "") or ""),
        "name": _humanize_identifier(str(getattr(spec, "id", "") or "")) or "Package Tool",
        "description": str(getattr(spec, "description", "") or ""),
        "risk_level": str(getattr(spec, "risk_level", "") or "low"),
        "concurrent": bool(getattr(spec, "concurrent", True)),
    }


def _public_knowledge_source(source: dict[str, Any], *, document_count: int | None = None) -> dict[str, Any]:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    return {
        "source_id": source.get("source_id"),
        "name": str(source.get("display_name") or source.get("name") or source.get("source_id") or "知识源"),
        "kind": source.get("source_type"),
        "status": source.get("status"),
        "mode": source.get("mount_mode"),
        "uri": source.get("original_uri") or source.get("uri"),
        "updated_at": source.get("updated_at"),
        "document_count": document_count if document_count is not None else metadata.get("document_count"),
        "sample_titles": metadata.get("sample_titles") if isinstance(metadata.get("sample_titles"), list) else [],
    }


def _session_updated_sort_key(session: dict[str, Any]) -> str:
    return str(session.get("updated_at") or session.get("created_at") or "")


def _normalized_source_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source = dict(payload or {})
    kind = str(source.get("kind") or source.get("source_kind") or "").strip()
    source_type = str(source.get("source_type") or _source_type_from_kind(kind) or "filesystem").strip()
    display_name = str(source.get("display_name") or source.get("name") or source.get("title") or "").strip()
    metadata = dict(source.get("metadata") or {})
    if display_name:
        metadata.setdefault("display_name", display_name)
        metadata.setdefault("title", display_name)
    uri = str(source.get("uri") or source.get("path") or source.get("url") or "").strip()
    if source_type == "manual_note":
        content = str(source.get("content") or metadata.get("content") or uri).strip()
        metadata["content"] = content
        uri = content
    result = {
        "source_type": source_type,
        "mount_mode": str(source.get("mount_mode") or source.get("mode") or "index_only").strip(),
        "uri": uri,
        "metadata": metadata,
    }
    if display_name:
        result["display_name"] = display_name
    source_id = str(source.get("source_id") or "").strip()
    if source_id:
        result["source_id"] = source_id
    if source.get("ingestion_plan") is not None:
        result["ingestion_plan"] = source.get("ingestion_plan")
    return result


def _source_type_from_kind(kind: str) -> str | None:
    if kind in {"folder", "file", "filesystem"}:
        return "filesystem"
    if kind in {"url", "web", "web_snapshot"}:
        return "web_snapshot"
    if kind in {"note", "manual_note"}:
        return "manual_note"
    return None
