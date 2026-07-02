from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import base64
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
from typing import Any, Iterator
from uuid import uuid4
import zipfile

from agent_factory.document_processing import EMAIL_EXTENSIONS, OFFICE_EXTENSIONS, parse_file
from agent_factory.knowledge_system import KnowledgeCatalog, KnowledgeRuntime
from agent_factory.knowledge_system.schema import KnowledgeContractConfig
from agent_factory.runtime_contracts import AgentPackageLoader, LoadedAgentPackage
from agent_factory.runtime_kernel.session import AgentSessionConfig, AgentSessionManager
from agent_factory.runtime_kernel.extensions.loader import (
    AgentInstanceExtensionConfigLoader,
    default_builtin_agent_extension_root,
)
from agent_factory.mcp_gateway import HostMCPGatewayManager
from agent_factory.skillhub_gateway import HostSkillHubGatewayManager
from agent_factory.package_runtime import host_runtime_package_view
from agent_factory.package_runtime.request_lifecycle import RuntimeRequestPolicy
from agent_factory.paths import factory_artifact_path, project_root
from agent_factory.runtime_attachments import (
    ATTACHMENT_INPUT_DIR,
    AttachmentImportResult,
    import_runtime_attachments,
    time_named_attachment_scope,
)
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent, event
from agent_factory.factory_graph.frontend_bridge.agent_runtime_launcher import (
    AgentRuntimeLaunchError,
    DockerAgentRuntimeLauncher,
)
from agent_factory.factory_graph.frontend_bridge.container_runtime_handle import AgentRuntimeContainerHandle
from agent_factory.factory_graph.frontend_bridge.runtime_events import node_event, run_failed_event
from agent_factory.factory_graph.frontend_bridge.system_package_runtime_handle import SystemPackageRuntimeHandle
from agent_factory.tooling.mcp_runtime import MCPRuntimeManager
from agent_factory.tooling.providers import (
    EnabledSkillConfig,
    EnabledSkillsConfig,
    MCPServerConfig,
    MCPServersConfig,
)
from agent_factory.tooling.skills import parse_skill_directory


DEFAULT_AGENT_PACKAGE_ROOT = ".agentfactory/packages"
DEFAULT_SYSTEM_PACKAGE_ROOT = "SystemPackage"
DEFAULT_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS = 1800
WORKSPACE_BINARY_PREVIEW_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".ico",
    ".zip",
    ".gz",
    ".tar",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
}
Emit = Callable[[FactoryFrontendEvent], None]


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
        launcher: DockerAgentRuntimeLauncher | None = None,
        emit: Emit | None = None,
    ) -> None:
        configured_root = package_root or os.getenv("AGENTFACTORY_PACKAGE_ROOT")
        self.package_root = Path(configured_root).expanduser() if configured_root else _default_package_root()
        configured_system_root = system_package_root or os.getenv("AGENTFACTORY_SYSTEM_PACKAGE_ROOT")
        self.system_package_root = (
            Path(configured_system_root).expanduser() if configured_system_root else _default_system_package_root()
        )
        self.loader = AgentPackageLoader()
        self.launcher = launcher or DockerAgentRuntimeLauncher()
        self.idle_timeout_seconds = _env_int(
            "AGENTFACTORY_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS",
            DEFAULT_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS,
        )
        self.request_policy = RuntimeRequestPolicy.from_env()
        self._containers: dict[str, AgentRuntimeContainerHandle] = {}
        self._system_handles: dict[str, SystemPackageRuntimeHandle] = {}
        self._instance_status_overrides: dict[str, dict[str, Any]] = {}
        self._mcp_gateways = HostMCPGatewayManager()
        self._skillhub_gateways = HostSkillHubGatewayManager()
        self._emit = emit
        self._context_window_tokens: int | None = None
        self._env_overrides: dict[str, str] = {}

    def set_emit(self, emit: Emit | None) -> None:
        self._emit = emit
        for handle in self._containers.values():
            handle.set_emit(emit)
        for handle in self._system_handles.values():
            handle.set_emit(emit)

    def set_context_window_tokens(self, value: int | None) -> None:
        self._context_window_tokens = value if isinstance(value, int) and value > 0 else None
        resources = self._runtime_resource_overrides()
        for handle in self._system_handles.values():
            handle.set_runtime_resources_override(resources)

    def set_env_overrides(self, overrides: dict[str, str] | None) -> None:
        next_overrides = dict(overrides or {})
        if next_overrides == self._env_overrides:
            return
        self._env_overrides = next_overrides
        self.close_all()

    def list_packages(self) -> list[dict[str, Any]]:
        self.package_root.mkdir(parents=True, exist_ok=True)
        packages: list[dict[str, Any]] = []
        for manifest_path in sorted(self.package_root.glob("*/agent_package.json")):
            packages.append(self._package_summary(manifest_path))
        return sorted(packages, key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    def list_instance_statuses(self) -> list[dict[str, Any]]:
        package_ids = {item.get("package_id") for item in self.list_packages()}
        package_ids.update(self._containers)
        package_ids.update(self._system_handles)
        return [
            self.package_instance_status(str(package_id))
            for package_id in sorted(item for item in package_ids if item)
        ]

    def package_instance_status(self, package_id: str) -> dict[str, Any]:
        package = self.loader.load_path(self._manifest_path(package_id))
        backend = "host" if _is_host_system_package(package) else "container"
        handle = self._system_handles.get(package_id) if backend == "host" else self._containers.get(package_id)
        running = bool(handle is not None and getattr(handle, "is_running", False))
        active_request_count = int(getattr(handle, "active_request_count", 0)) if handle is not None else 0
        active_command_types = set(getattr(handle, "active_command_types", ())) if handle is not None else set()
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
        package = self.loader.load_path(self._manifest_path(package_id))
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
                    request_id=None,
                    mode="agent_package",
                    graph_id="agent_package_runtime",
                    producer_type="factory_runtime",
                    payload=initializing_status,
                )
            )
        command = {
            "type": "initialize_runtime",
            "request_id": request_id or uuid4().hex,
            "payload": {},
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
        self._close_container(package_id)
        self._close_system(package_id)
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

    def scheduler_events(
        self,
        package_id: str,
        *,
        payload: dict[str, Any],
        request_id: str | None = None,
    ) -> Iterator[tuple[str, Any]]:
        package = self.loader.load_path(self._manifest_path(package_id))
        command = {
            "type": "scheduler_manage",
            "request_id": request_id or uuid4().hex,
            "payload": dict(payload),
        }
        yield from self._runtime_events(package_id, package=package, command=command)

    def package_summary(self, package_id: str) -> dict[str, Any]:
        return self._package_summary(self._manifest_path(package_id))

    def delete_package(self, package_id: str) -> dict[str, Any]:
        self._close_container(package_id)
        target = self._package_dir(package_id, include_system_packages=False)
        if not target.exists():
            raise FileNotFoundError(f"agent package not found: {package_id}")
        shutil.rmtree(target)
        return {"package_id": package_id, "deleted": True}

    def export_package_archive(self, package_id: str) -> Path:
        target = self._package_dir(package_id, include_system_packages=False)
        manifest_path = target / "agent_package.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"agent package not found: {package_id}")
        archive_stem = _safe_archive_stem(package_id)
        with tempfile.NamedTemporaryFile(prefix=f"{archive_stem}-", suffix=".zip", delete=False) as handle:
            archive_path = Path(handle.name)
        root_name = target.name
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(item for item in target.rglob("*") if item.is_file()):
                if path.is_symlink():
                    continue
                relative_path = Path(root_name) / path.relative_to(target)
                archive.write(path, relative_path.as_posix())
        return archive_path

    def list_sessions(self, package_id: str) -> list[dict[str, Any]]:
        package = self.loader.load_path(self._manifest_path(package_id))
        return self._list_sessions_for_loaded_package(package)

    def load_session(self, package_id: str, session_id: str) -> dict[str, Any]:
        package = self.loader.load_path(self._manifest_path(package_id))
        return self._session_manager_for_package(package_id, package).load(session_id).model_dump(mode="json")

    def workspace_roots(self, package_id: str) -> dict[str, Any]:
        package = self.loader.load_path(self._manifest_path(package_id))
        roots = self._workspace_roots(package_id, package)
        return {
            "package_id": package_id,
            "roots": [
                {"scope": scope, "name": _workspace_scope_label(scope), "exists": path.exists()}
                for scope, path in roots.items()
            ],
        }

    def list_workspace_entries(
        self,
        package_id: str,
        *,
        scope: str = "workdir",
        relative_path: str = "",
    ) -> dict[str, Any]:
        package = self.loader.load_path(self._manifest_path(package_id))
        root = self._workspace_scope_root(package_id, package, scope)
        target = _safe_workspace_path(root, relative_path)
        if not target.exists():
            return {"package_id": package_id, "scope": scope, "path": relative_path, "entries": []}
        if target.is_file():
            entries = [_workspace_entry(target, root=root, scope=scope)]
        else:
            entries = [_workspace_entry(path, root=root, scope=scope) for path in sorted(target.iterdir(), key=_workspace_sort_key)]
        return {"package_id": package_id, "scope": scope, "path": relative_path, "entries": entries}

    def read_workspace_file(
        self,
        package_id: str,
        *,
        scope: str = "workdir",
        relative_path: str,
        max_chars: int = 20000,
    ) -> dict[str, Any]:
        package = self.loader.load_path(self._manifest_path(package_id))
        root = self._workspace_scope_root(package_id, package, scope)
        target = _safe_workspace_path(root, relative_path)
        if not target.is_file():
            raise FileNotFoundError(f"workspace file not found: {relative_path}")
        stat = target.stat()
        byte_limit = max(4096, max_chars * 4)
        with target.open("rb") as handle:
            data = handle.read(byte_limit + 1)
        mime_type, _ = mimetypes.guess_type(target.name)
        is_binary = _workspace_file_is_binary(target=target, data=data, mime_type=mime_type)
        content = ""
        content_base64 = ""
        preview_mode = "binary"
        truncated = stat.st_size > byte_limit
        extracted_text = _workspace_extracted_text_preview(target=target, root=root, max_chars=max_chars)
        if extracted_text is not None:
            content, extracted_truncated = extracted_text
            is_binary = False
            preview_mode = "extracted_text"
            truncated = extracted_truncated
        elif not is_binary:
            text = data.decode("utf-8", errors="replace")
            truncated = truncated or len(text) > max_chars
            content = text[:max_chars]
            preview_mode = "text"
        else:
            preview_bytes = data[:byte_limit]
            content_base64 = base64.b64encode(preview_bytes).decode("ascii")
        return {
            "package_id": package_id,
            "scope": scope,
            "path": target.relative_to(root).as_posix(),
            "name": target.name,
            "kind": "binary" if is_binary else "text",
            "mime_type": mime_type or "application/octet-stream",
            "encoding": "base64" if is_binary else "utf-8",
            "size_bytes": stat.st_size,
            "content": content,
            "content_base64": content_base64,
            "preview_mode": preview_mode,
            "truncated": truncated,
        }

    def resolve_workspace_file(
        self,
        package_id: str,
        *,
        scope: str = "workdir",
        relative_path: str,
    ) -> Path:
        package = self.loader.load_path(self._manifest_path(package_id))
        root = self._workspace_scope_root(package_id, package, scope)
        target = _safe_workspace_path(root, relative_path)
        if not target.is_file():
            raise FileNotFoundError(f"workspace file not found: {relative_path}")
        return target

    def extension_config_summary(self, package_id: str) -> dict[str, Any]:
        package = self.loader.load_path(self._manifest_path(package_id))
        extension_root = _extension_root_for_package(package_id, package)
        bundle = _load_extension_bundle(extension_root, package=package)
        return {
            "package_id": package_id,
            "mcp_servers": [_public_mcp_server(server.model_dump(mode="json")) for server in bundle.mcp_servers.servers],
            "skills": [_public_skill(skill.model_dump(mode="json")) for skill in bundle.enabled_skills.skills],
            "sources": {
                "extension_root": str(bundle.sources.extension_root),
                "mcp_servers_paths": [str(path) for path in bundle.sources.mcp_servers_paths],
                "enabled_skills_paths": [str(path) for path in bundle.sources.enabled_skills_paths],
            },
        }

    def extensions_manage(self, package_id: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        package = self.loader.load_path(self._manifest_path(package_id))
        extension_root = _extension_root_for_package(package_id, package)
        if action == "list":
            return self.extension_config_summary(package_id)
        if action == "upsert_mcp":
            server = _mcp_server_for_upsert(extension_root, payload, package=package)
            _save_mcp_server(extension_root, server)
            self._close_container(package_id)
            self._close_system(package_id)
            return {"updated": "mcp", "server": _public_mcp_server(server.model_dump(mode="json")), **self.extension_config_summary(package_id)}
        if action == "set_mcp_enabled":
            server_id = _required_config_id(payload, "server_id")
            server = _set_mcp_server_enabled(extension_root, server_id=server_id, enabled=bool(payload.get("enabled", True)))
            self._close_container(package_id)
            self._close_system(package_id)
            return {"updated": "mcp", "server": _public_mcp_server(server.model_dump(mode="json")), **self.extension_config_summary(package_id)}
        if action == "remove_mcp":
            server_id = _required_config_id(payload, "server_id")
            removed = _remove_mcp_server(extension_root, server_id=server_id)
            self._close_container(package_id)
            self._close_system(package_id)
            return {"updated": "mcp", "removed": removed, **self.extension_config_summary(package_id)}
        if action == "test_mcp":
            server = _mcp_server_for_test(extension_root, payload, package=package)
            return {"test": _test_mcp_server(server), **self.extension_config_summary(package_id)}
        if action == "upsert_skill":
            skill_payload = payload.get("skill") if isinstance(payload.get("skill"), dict) else payload
            skill = _skill_from_payload(skill_payload, extension_root=extension_root)
            replace_skill_id = str(payload.get("replace_skill_id") or skill_payload.get("replace_skill_id") or "").strip()
            if replace_skill_id and replace_skill_id != skill.skill_id:
                _remove_enabled_skill(extension_root, skill_id=replace_skill_id)
            _save_enabled_skill(extension_root, skill)
            self._close_container(package_id)
            self._close_system(package_id)
            return {"updated": "skill", "skill": _public_skill(skill.model_dump(mode="json")), **self.extension_config_summary(package_id)}
        if action == "set_skill_enabled":
            skill_id = _required_config_id(payload, "skill_id")
            skill = _set_skill_enabled(extension_root, skill_id=skill_id, enabled=bool(payload.get("enabled", True)))
            self._close_container(package_id)
            self._close_system(package_id)
            return {"updated": "skill", "skill": _public_skill(skill.model_dump(mode="json")), **self.extension_config_summary(package_id)}
        if action == "remove_skill":
            skill_id = _required_config_id(payload, "skill_id")
            removed = _remove_enabled_skill(extension_root, skill_id=skill_id)
            self._close_container(package_id)
            self._close_system(package_id)
            return {"updated": "skill", "removed": removed, **self.extension_config_summary(package_id)}
        raise ValueError(f"unsupported extensions action: {action}")

    def knowledge_runtime_for_package(self, package_id: str) -> KnowledgeRuntime:
        package = self.loader.load_path(self._manifest_path(package_id))
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
        return KnowledgeRuntime(
            config=config,
            owner_type="agent",
            owner_id=package.assembly_spec.agent.id,
            catalog=KnowledgeCatalog(config.catalog_path),
            store=None,
        )

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
    ) -> dict[str, Any]:
        package = self.loader.load_path(self._manifest_path(package_id))
        manager = self._session_manager_for_package(package_id, package)
        if session_id:
            try:
                return manager.load(session_id).model_dump(mode="json")
            except FileNotFoundError:
                pass
        return manager.create(
            agent_id=package.assembly_spec.agent.id,
            first_user_input=first_user_input,
        ).model_dump(mode="json")

    def run(self, package_id: str, *, user_input: str, session_id: str | None = None) -> AgentPackageRunResult:
        raise RuntimeError("AgentPackage host-process execution is disabled; use stream() for sandbox execution.")

    def stream(
        self,
        package_id: str,
        *,
        user_input: str,
        session_id: str | None = None,
        request_id: str | None = None,
        user_config: dict[str, Any] | None = None,
        attachments: Any = None,
        require_ready: bool = False,
    ) -> AgentPackageStreamRun:
        package = self.loader.load_path(self._manifest_path(package_id))
        if require_ready and not self._has_ready_runtime(package_id, package):
            raise RuntimeError(f"agent package instance is not ready: {package_id}")
        resolved_request_id = request_id or uuid4().hex
        attachment_result = self._prepare_runtime_attachments(
            package_id=package_id,
            package=package,
            user_input=user_input,
            attachments=attachments,
        )
        command = {
            "type": "run_message",
            "request_id": resolved_request_id,
            "payload": {
                "message": attachment_result.message,
                "session_id": session_id,
                "user_config": dict(user_config or {}),
                "attachments": attachment_result.attachments,
                "runtime_request": self.request_policy.as_payload(),
            },
        }
        if _is_host_system_package(package):
            return AgentPackageStreamRun(
                package=package,
                session={"session_id": session_id} if session_id else {},
                events=self._system_events(package_id, package=package, command=command),
            )
        return AgentPackageStreamRun(
            package=package,
            session={"session_id": session_id} if session_id else {},
            events=self._container_events(package_id, package=package, command=command),
        )

    def _prepare_runtime_attachments(
        self,
        *,
        package_id: str,
        package: LoadedAgentPackage,
        user_input: str,
        attachments: Any,
    ) -> AttachmentImportResult:
        runtime_root = _host_runtime_root(package_id)
        workdir_root = runtime_root / "workdir"
        attachment_scope = time_named_attachment_scope()
        runtime_path_root = (
            str(workdir_root / ATTACHMENT_INPUT_DIR / attachment_scope)
            if _is_host_system_package(package)
            else f"/workdir/{ATTACHMENT_INPUT_DIR}/{attachment_scope}"
        )
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
    ) -> AgentPackageStreamRun:
        package = self.loader.load_path(self._manifest_path(package_id))
        session = self._session_manager_for_package(package_id, package).load(session_id)
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
                events=self._system_events(package_id, package=package, command=command),
            )
        return AgentPackageStreamRun(
            package=package,
            session=session.model_dump(mode="json"),
            events=self._container_events(package_id, package=package, command=command),
        )

    def _package_summary(self, manifest_path: Path) -> dict[str, Any]:
        package_id = manifest_path.parent.name
        try:
            package = self.loader.load_path(manifest_path)
            report = _read_json_object(manifest_path.parent / "package_report.json")
            sessions = self._list_sessions_for_loaded_package(package)
            sandbox = _sandbox_summary(package.sandbox_contract)
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
                "sandbox": sandbox,
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
                "sandbox": {"status": "unknown"},
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
        for package_id in list(self._containers):
            self._close_container(package_id)
        for package_id in list(self._system_handles):
            self._close_system(package_id)
        self._mcp_gateways.close_all()
        self._skillhub_gateways.close_all()

    def cancel_active_requests(self, *, reason: str = "user_cancelled") -> int:
        cancelled = 0
        for handle in list(self._containers.values()):
            cancelled += handle.cancel_active_requests(reason=reason)
        for handle in list(self._system_handles.values()):
            cancelled += handle.cancel_active_requests(reason=reason)
        return cancelled

    def _system_events(
        self,
        package_id: str,
        *,
        package: LoadedAgentPackage,
        command: dict[str, Any],
    ) -> Iterator[tuple[str, Any]]:
        request_id = str(command.get("request_id") or uuid4().hex)
        command["request_id"] = request_id
        will_start = not self._has_reusable_system_handle(package_id, package)
        if will_start:
            yield "frontend_event", node_event(
                request_id,
                "node_started",
                node_id="runtime_container",
                payload={"package_id": package_id, "backend": "host", "status": "preflight"},
            )
        try:
            handle = self._system_handle(package_id, package)
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
    ) -> Iterator[tuple[str, Any]]:
        request_id = str(command.get("request_id") or uuid4().hex)
        command["request_id"] = request_id
        will_start = not self._has_reusable_container(package_id, package)
        if will_start:
            yield "frontend_event", node_event(
                request_id,
                "node_started",
                node_id="runtime_container",
                payload={"package_id": package_id, "status": "preflight"},
            )
        try:
            handle = self._container(package_id, package)
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
            self._close_container(package_id)
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

    def _container(self, package_id: str, package: LoadedAgentPackage) -> "AgentRuntimeContainerHandle":
        existing = self._containers.get(package_id)
        fingerprint = _runtime_fingerprint(package_id, package)
        if (
            existing is not None
            and existing.is_running
            and existing.package_fingerprint == fingerprint
            and not existing.is_idle(self.idle_timeout_seconds)
        ):
            return existing
        self._close_container(package_id)
        runtime_root = _host_runtime_root(package_id)
        artifacts_root = runtime_root / "artifacts" / uuid4().hex
        workdir_root = runtime_root / "workdir"
        extension_root = _extension_root_for_package(package_id, package)
        for path in (artifacts_root, workdir_root, runtime_root, extension_root):
            path.mkdir(parents=True, exist_ok=True)
        fingerprint = _runtime_fingerprint(package_id, package)
        mcp_gateway = self._mcp_gateways.ensure_gateway(
            _load_extension_bundle(extension_root, package=package).mcp_servers
        )
        skillhub_gateway = self._skillhub_gateways.ensure_gateway(extension_root)
        plan = self.launcher.prepare(
            package=package,
            runtime_root=runtime_root,
            artifacts_root=artifacts_root,
            workdir_root=workdir_root,
            extension_root=extension_root,
            mcp_gateway_url=mcp_gateway.docker_url if mcp_gateway is not None else None,
            skillhub_gateway_url=skillhub_gateway.docker_url,
            env_overrides=self._runtime_env_overrides(),
        )
        handle = AgentRuntimeContainerHandle(
            package_id=package_id,
            package_fingerprint=fingerprint,
            idle_timeout_seconds=self.idle_timeout_seconds,
            request_policy=self.request_policy,
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
        }
        self._containers[package_id] = handle
        return handle

    def _system_handle(self, package_id: str, package: LoadedAgentPackage) -> "SystemPackageRuntimeHandle":
        existing = self._system_handles.get(package_id)
        fingerprint = _runtime_fingerprint(package_id, package)
        if (
            existing is not None
            and existing.package_fingerprint == fingerprint
            and not existing.is_idle(self.idle_timeout_seconds)
        ):
            return existing
        self._close_system(package_id)
        runtime_root = _host_runtime_root(package_id)
        artifacts_root = runtime_root / "artifacts"
        workdir_root = runtime_root / "workdir"
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
            idle_timeout_seconds=self.idle_timeout_seconds,
            request_policy=self.request_policy,
            producer_type="factory_runtime" if _is_system_package(package) else "agent_runtime_host",
            emit=self._emit,
        )
        handle.set_runtime_resources_override(self._runtime_resource_overrides())
        handle.startup_payload = {
            "status": "running",
            "backend": "host",
            "package_id": package_id,
            "runtime_root": str(runtime_root),
            "artifact_root": str(artifacts_root),
            "workdir": str(workdir_root),
            "extension_root": str(extension_root),
        }
        self._system_handles[package_id] = handle
        return handle

    def _runtime_env_overrides(self) -> dict[str, str]:
        result = dict(self._env_overrides)
        if self._context_window_tokens is not None:
            result["AGENTFACTORY_CONTEXT_WINDOW_TOKENS"] = str(self._context_window_tokens)
        return result

    def _runtime_resource_overrides(self) -> dict[str, Any]:
        if self._context_window_tokens is None:
            return {}
        return {"context_window_tokens": self._context_window_tokens}

    def _has_reusable_container(self, package_id: str, package: LoadedAgentPackage) -> bool:
        existing = self._containers.get(package_id)
        if existing is None or not existing.is_running:
            return False
        if existing.package_fingerprint != _runtime_fingerprint(package_id, package):
            return False
        return not existing.is_idle(self.idle_timeout_seconds)

    def _has_reusable_system_handle(self, package_id: str, package: LoadedAgentPackage) -> bool:
        existing = self._system_handles.get(package_id)
        if existing is None:
            return False
        if existing.package_fingerprint != _runtime_fingerprint(package_id, package):
            return False
        return not existing.is_idle(self.idle_timeout_seconds)

    def _has_ready_runtime(self, package_id: str, package: LoadedAgentPackage) -> bool:
        if _is_host_system_package(package):
            return self._has_reusable_system_handle(package_id, package)
        return self._has_reusable_container(package_id, package)

    def _close_container(self, package_id: str) -> None:
        handle = self._containers.pop(package_id, None)
        self._instance_status_overrides.pop(package_id, None)
        if handle is not None:
            handle.close()

    def _close_system(self, package_id: str) -> None:
        handle = self._system_handles.pop(package_id, None)
        self._instance_status_overrides.pop(package_id, None)
        if handle is not None:
            handle.close()

    def _manifest_path(self, package_id: str) -> Path:
        return self._package_dir(package_id) / "agent_package.json"

    def _package_dir(self, package_id: str, *, include_system_packages: bool = True) -> Path:
        if not package_id or "/" in package_id or "\\" in package_id or package_id in {".", ".."}:
            raise ValueError(f"invalid agent package id: {package_id}")
        user_target = _safe_child(self.package_root, package_id, label="agent package")
        if user_target.exists() or not include_system_packages:
            return user_target
        system_target = _safe_child(self.system_package_root, package_id, label="system package")
        if system_target.exists():
            return system_target
        return user_target

    def _workspace_roots(self, package_id: str, package: LoadedAgentPackage) -> dict[str, Path]:
        runtime_root = _host_runtime_root(package_id)
        return {
            "package": package.package_root,
            "runtime": runtime_root,
            "workdir": runtime_root / "workdir",
            "artifacts": runtime_root / "artifacts",
            "extensions": _extension_root_for_package(package_id, package),
        }

    def _workspace_scope_root(self, package_id: str, package: LoadedAgentPackage, scope: str) -> Path:
        roots = self._workspace_roots(package_id, package)
        normalized = str(scope or "workdir").strip()
        if normalized not in roots:
            raise ValueError(f"unsupported workspace scope: {scope}")
        return roots[normalized].resolve()


def _workspace_scope_label(scope: str) -> str:
    labels = {
        "package": "Package",
        "runtime": "Runtime",
        "workdir": "Workdir",
        "artifacts": "Artifacts",
        "extensions": "Extensions",
    }
    return labels.get(scope, _humanize_identifier(scope))


def _workspace_file_is_binary(*, target: Path, data: bytes, mime_type: str | None) -> bool:
    suffix = target.suffix.lower()
    if suffix in WORKSPACE_BINARY_PREVIEW_EXTENSIONS:
        return True
    if suffix == ".svg":
        return False
    normalized_mime = str(mime_type or "").lower()
    if normalized_mime.startswith("image/"):
        return True
    if normalized_mime in {"application/pdf", "application/zip", "application/octet-stream"}:
        return True
    return b"\x00" in data[:4096]


def _workspace_extracted_text_preview(*, target: Path, root: Path, max_chars: int) -> tuple[str, bool] | None:
    if target.suffix.lower() not in (OFFICE_EXTENSIONS | EMAIL_EXTENSIONS):
        return None
    try:
        result = parse_file(target, root=root)
    except Exception:
        return None
    content = "\n\n".join(document.content.strip() for document in result.documents if document.content.strip()).strip()
    if not content:
        return None
    return content[:max_chars], len(content) > max_chars


def _safe_workspace_path(root: Path, relative_path: str | os.PathLike[str] | None) -> Path:
    resolved_root = root.resolve()
    raw_path = str(relative_path or "").strip()
    if not raw_path:
        return resolved_root
    path = Path(raw_path)
    if path.is_absolute():
        raise ValueError("workspace path must be relative to its selected scope")
    target = (resolved_root / path).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"workspace path escapes selected scope: {raw_path}") from exc
    return target


def _workspace_entry(path: Path, *, root: Path, scope: str) -> dict[str, Any]:
    try:
        stat = path.stat()
        size_bytes = stat.st_size if path.is_file() else None
        updated_at = datetime.fromtimestamp(stat.st_mtime, UTC).isoformat()
    except OSError:
        size_bytes = None
        updated_at = None
    try:
        relative_path = path.relative_to(root).as_posix()
    except ValueError:
        relative_path = path.name
    return {
        "name": path.name,
        "scope": scope,
        "path": "" if relative_path == "." else relative_path,
        "kind": "directory" if path.is_dir() else "file",
        "size_bytes": size_bytes,
        "updated_at": updated_at,
    }


def _workspace_sort_key(path: Path) -> tuple[int, str]:
    return (0 if path.is_dir() else 1, path.name.lower())


def _host_runtime_root(package_id: str) -> Path:
    return factory_artifact_path("agent_runtime", package_id)


def _host_session_root(*, package_id: str, package: LoadedAgentPackage, configured: str) -> Path:
    value = configured.strip()
    runtime_root = _host_runtime_root(package_id)
    if value == "/runtime":
        return runtime_root.resolve()
    if value.startswith("/runtime/"):
        return _root_relative_path(
            runtime_root,
            Path(value.removeprefix("/runtime/")),
            field_path="session.config.session_root",
        )
    if value == ".agent_runtime":
        return runtime_root.resolve()
    if value.startswith(".agent_runtime/"):
        return _root_relative_path(
            runtime_root,
            Path(value.removeprefix(".agent_runtime/")),
            field_path="session.config.session_root",
        )
    path = Path(value).expanduser()
    if path.is_absolute():
        raise ValueError(
            "session.config.session_root must be package-relative or use /runtime/... "
            f"when a runtime workspace is mounted; got {value!r}"
        )
    return _root_relative_path(package.package_root, path, field_path="session.config.session_root")


def _root_relative_path(root_path: Path, path: Path, *, field_path: str) -> Path:
    root = root_path.resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field_path} must resolve inside its runtime workspace; got {str(path)!r}") from exc
    return target


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


def _default_package_root() -> Path:
    return project_root() / DEFAULT_AGENT_PACKAGE_ROOT


def _default_system_package_root() -> Path:
    return project_root() / DEFAULT_SYSTEM_PACKAGE_ROOT


def _default_project_root() -> Path:
    return project_root()


def _safe_child(root: Path, child_name: str, *, label: str) -> Path:
    resolved_root = root.resolve()
    target = (resolved_root / child_name).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes package root: {child_name}") from exc
    return target


def _safe_archive_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return stem or "agent-package"


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
        digest.update(_runtime_image_identity(package).encode("utf-8"))
    return digest.hexdigest()


def _runtime_fingerprint(package_id: str, package: LoadedAgentPackage) -> str:
    digest = hashlib.sha256()
    digest.update(_package_fingerprint(package).encode("utf-8"))
    extension_root = _extension_root_for_package(package_id, package)
    digest.update(b"runtime-extension-root")
    digest.update(str(extension_root.resolve()).encode("utf-8"))
    _hash_tree(digest, extension_root)
    return digest.hexdigest()


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


def _runtime_image_identity(package: LoadedAgentPackage) -> str:
    image = str((package.sandbox_contract or {}).get("image") or "")
    if not image:
        return "image:"
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


def _sandbox_summary(contract: dict[str, Any]) -> dict[str, Any]:
    backend = contract.get("backend")
    if not backend and isinstance(contract.get("config"), dict):
        backend = contract["config"].get("backend")
    return {
        "status": "contract_ready" if contract else "missing_contract",
        "backend": backend or "unknown",
    }


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


def _package_extension_detail(*, package_id: str, package: LoadedAgentPackage) -> dict[str, Any]:
    extension_root = _extension_root_for_package(package_id, package)
    try:
        bundle = _load_extension_bundle(extension_root, package=package)
        return {
            "mcp_servers": [
                _public_mcp_server(server.model_dump(mode="json"))
                for server in bundle.mcp_servers.servers
            ],
            "skills": [
                _public_skill(skill.model_dump(mode="json"))
                for skill in bundle.enabled_skills.skills
            ],
        }
    except Exception as exc:
        return {
            "mcp_servers": [],
            "skills": [],
            "extensions_error": f"{type(exc).__name__}: {exc}",
        }


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


def _extension_root_for_package(package_id: str, package: LoadedAgentPackage) -> Path:
    if _is_system_package(package):
        return package.package_root.parent / "extensions"
    return _host_runtime_root(package_id) / "extensions"


def _merge_extension_config(
    *,
    source_path: Path,
    target_path: Path,
    list_key: str,
    id_key: str,
    default_version: str,
    override_existing: bool,
) -> None:
    source_payload = _read_json_object(source_path)
    source_items = source_payload.get(list_key)
    if not isinstance(source_items, list) or not source_items:
        return
    target_payload = _read_json_object(target_path)
    target_items = target_payload.get(list_key)
    if not isinstance(target_items, list):
        target_items = []
    existing = [
        str(item.get(id_key) or "")
        for item in target_items
        if isinstance(item, dict)
    ]
    merged = list(target_items)
    for item in source_items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get(id_key) or "")
        if not item_id:
            continue
        if item_id in existing:
            if override_existing:
                merged[existing.index(item_id)] = item
            continue
        merged.append(item)
        existing.append(item_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(
        json.dumps(
            {
                "version": str(target_payload.get("version") or source_payload.get("version") or default_version),
                list_key: merged,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _is_system_package(package: LoadedAgentPackage) -> bool:
    return bool(package.manifest.runtime.get("system_package"))


def _is_host_system_package(package: LoadedAgentPackage) -> bool:
    if not _is_system_package(package):
        return False
    backend = str(package.manifest.runtime.get("execution_backend") or "host").strip().lower()
    return backend == "host"


def _extensions_summary(package_id: str, *, package: LoadedAgentPackage | None = None) -> dict[str, str]:
    host_root = (
        _extension_root_for_package(package_id, package)
        if package is not None
        else _host_runtime_root(package_id) / "extensions"
    )
    return {
        "host_root": str(host_root),
        "container_root": "/runtime/extensions",
    }


def _load_extension_bundle(extension_root: Path, *, package: LoadedAgentPackage | None = None) -> Any:
    return AgentInstanceExtensionConfigLoader(
        extension_root,
        inherited_extension_roots=_extension_inherited_roots(extension_root, package=package),
    ).load()


def _extension_inherited_roots(extension_root: Path, *, package: LoadedAgentPackage | None) -> list[Path]:
    if package is None:
        return []
    roots: list[Path] = []
    if _is_system_package(package):
        builtin_root = default_builtin_agent_extension_root()
        if builtin_root.resolve() != extension_root.resolve():
            roots.append(builtin_root)
    package_extension_root = package.package_root / "extensions"
    if package_extension_root.resolve() != extension_root.resolve():
        roots.append(package_extension_root)
    return roots


def _load_local_mcp_config(extension_root: Path) -> MCPServersConfig:
    return MCPServersConfig.model_validate(_read_json_object(extension_root / "mcp_servers.json") or {})


def _write_local_mcp_config(extension_root: Path, config: MCPServersConfig) -> None:
    _write_json_object(extension_root / "mcp_servers.json", config.model_dump(mode="json"))


def _load_local_skills_config(extension_root: Path) -> EnabledSkillsConfig:
    return EnabledSkillsConfig.model_validate(_read_json_object(extension_root / "enabled_skills.json") or {})


def _write_local_skills_config(extension_root: Path, config: EnabledSkillsConfig) -> None:
    _write_json_object(extension_root / "enabled_skills.json", config.model_dump(mode="json"))


def _save_mcp_server(extension_root: Path, server: MCPServerConfig) -> None:
    config = _load_local_mcp_config(extension_root)
    servers = [item for item in config.servers if item.server_id != server.server_id]
    servers.append(server)
    _write_local_mcp_config(
        extension_root,
        config.model_copy(update={"servers": sorted(servers, key=lambda item: item.server_id)}),
    )


def _set_mcp_server_enabled(extension_root: Path, *, server_id: str, enabled: bool) -> MCPServerConfig:
    config = _load_local_mcp_config(extension_root)
    servers: list[MCPServerConfig] = []
    updated: MCPServerConfig | None = None
    for server in config.servers:
        if server.server_id == server_id:
            updated = server.model_copy(update={"enabled": enabled})
            servers.append(updated)
        else:
            servers.append(server)
    if updated is None:
        raise ValueError(f"MCP server is not configured: {server_id}")
    _write_local_mcp_config(extension_root, config.model_copy(update={"servers": servers}))
    return updated


def _remove_mcp_server(extension_root: Path, *, server_id: str) -> bool:
    config = _load_local_mcp_config(extension_root)
    servers = [server for server in config.servers if server.server_id != server_id]
    removed = len(servers) != len(config.servers)
    _write_local_mcp_config(extension_root, config.model_copy(update={"servers": servers}))
    return removed


def _save_enabled_skill(extension_root: Path, skill: EnabledSkillConfig) -> None:
    config = _load_local_skills_config(extension_root)
    skills = [item for item in config.skills if item.skill_id != skill.skill_id]
    skills.append(skill)
    _write_local_skills_config(extension_root, config.model_copy(update={"skills": sorted(skills, key=lambda item: item.skill_id)}))


def _set_skill_enabled(extension_root: Path, *, skill_id: str, enabled: bool) -> EnabledSkillConfig:
    config = _load_local_skills_config(extension_root)
    skills: list[EnabledSkillConfig] = []
    updated: EnabledSkillConfig | None = None
    for skill in config.skills:
        if skill.skill_id == skill_id:
            updated = skill.model_copy(update={"enabled": enabled})
            skills.append(updated)
        else:
            skills.append(skill)
    if updated is None:
        raise ValueError(f"Skill is not configured: {skill_id}")
    _write_local_skills_config(extension_root, config.model_copy(update={"skills": skills}))
    return updated


def _remove_enabled_skill(extension_root: Path, *, skill_id: str) -> bool:
    config = _load_local_skills_config(extension_root)
    skills = [skill for skill in config.skills if skill.skill_id != skill_id]
    removed = len(skills) != len(config.skills)
    _write_local_skills_config(extension_root, config.model_copy(update={"skills": skills}))
    return removed


def _mcp_server_for_upsert(
    extension_root: Path,
    payload: dict[str, Any],
    *,
    package: LoadedAgentPackage | None = None,
) -> MCPServerConfig:
    server_payload = payload.get("server") if isinstance(payload.get("server"), dict) else payload
    server_id = str(server_payload.get("server_id") or "").strip()
    existing = _find_mcp_server(extension_root, server_id, package=package) if server_id else None
    return _mcp_server_from_payload(server_payload, existing=existing)


def _find_mcp_server(
    extension_root: Path,
    server_id: str,
    *,
    package: LoadedAgentPackage | None = None,
) -> MCPServerConfig | None:
    if not server_id:
        return None
    try:
        bundle = _load_extension_bundle(extension_root, package=package)
    except Exception:
        bundle = None
    if bundle is not None:
        for server in bundle.mcp_servers.servers:
            if server.server_id == server_id:
                return server
    try:
        for server in _load_local_mcp_config(extension_root).servers:
            if server.server_id == server_id:
                return server
    except Exception:
        return None
    return None


def _mcp_server_for_test(
    extension_root: Path,
    payload: dict[str, Any],
    *,
    package: LoadedAgentPackage | None = None,
) -> MCPServerConfig:
    server_payload = payload.get("server") if isinstance(payload.get("server"), dict) else payload
    server_id = str(server_payload.get("server_id") or "").strip()
    if server_id:
        bundle = _load_extension_bundle(extension_root, package=package)
        for server in bundle.mcp_servers.servers:
            if server.server_id == server_id:
                existing = server
                return _mcp_server_from_payload(server_payload, existing=existing)
    return _mcp_server_from_payload(server_payload)


def _mcp_server_from_payload(payload: dict[str, Any], *, existing: MCPServerConfig | None = None) -> MCPServerConfig:
    raw = dict(payload or {})
    existing_source = dict(existing.source) if existing is not None else {}
    source = {**existing_source, **dict(raw.get("source") or {})}
    display_name = str(raw.get("display_name") or raw.get("name") or source.get("name") or "").strip()
    if display_name:
        source["name"] = display_name
    description = str(raw.get("description") or raw.get("summary") or source.get("description") or "").strip()
    if description:
        source["description"] = description
    command = str(raw.get("command") if "command" in raw else existing.command if existing is not None else "").strip()
    args = _parse_args(raw["args"]) if "args" in raw else list(existing.args) if existing is not None else []
    cwd_value = raw.get("cwd") if "cwd" in raw else existing.cwd if existing is not None else None
    cwd = str(cwd_value or "").strip() or None
    env = _parse_env(raw["env"]) if "env" in raw else dict(existing.env) if existing is not None else {}
    enabled = raw.get("enabled") if "enabled" in raw else existing.enabled if existing is not None else True
    server_id = _config_identifier(
        str(raw.get("server_id") or ""),
        fallback=display_name or str(source.get("package") or "") or command or "mcp_server",
    )
    return MCPServerConfig(
        server_id=server_id,
        transport=str(raw.get("transport") or (existing.transport if existing is not None else "stdio")).strip(),
        command=command or None,
        args=args,
        cwd=cwd,
        env=env,
        source=source,
        enabled=enabled is not False,
        required=bool(raw.get("required") if "required" in raw else existing.required if existing is not None else False),
        tool_id_prefix=_optional_identifier(raw.get("tool_id_prefix") if "tool_id_prefix" in raw else existing.tool_id_prefix if existing is not None else None),
        risk_level_default=str(raw.get("risk_level_default") or (existing.risk_level_default if existing is not None else "medium")),  # type: ignore[arg-type]
        concurrent_default=bool(raw.get("concurrent_default") if "concurrent_default" in raw else existing.concurrent_default if existing is not None else False),
        timeout_seconds=float(raw.get("timeout_seconds") or (existing.timeout_seconds if existing is not None else 30.0)),
    )


def _skill_from_payload(payload: dict[str, Any], *, extension_root: Path | None = None) -> EnabledSkillConfig:
    raw = dict(payload or {})
    path = str(raw.get("path") or "").strip()
    if not path:
        raise ValueError("Skill path is required")
    source = str(raw.get("source") or "local").strip() or "local"
    skill_id = str(raw.get("skill_id") or "").strip()
    if not skill_id:
        skill = parse_skill_directory(_skill_path_for_validation(path, extension_root))
        skill_id = skill.name
    return EnabledSkillConfig(
        skill_id=skill_id,
        enabled=raw.get("enabled", True) is not False,
        source=source,
        path=path,
        required=bool(raw.get("required")),
    )


def _skill_path_for_validation(path: str, extension_root: Path | None) -> str:
    skill_path = Path(path).expanduser()
    if not skill_path.is_absolute() and extension_root is not None:
        skill_path = extension_root / skill_path
    return str(skill_path)


def _test_mcp_server(server: MCPServerConfig) -> dict[str, Any]:
    manager = MCPRuntimeManager(MCPServersConfig(servers=[server.model_copy(update={"enabled": True})]))
    client = manager.clients().get(server.server_id)
    if client is None:
        return {"status": "failed", "message": "MCP server is disabled or unavailable", "tool_count": 0, "tools": []}
    try:
        tools = [tool.model_dump(mode="json") for tool in client.list_tools()]
    except Exception as exc:
        return {
            "status": "failed",
            "message": f"{type(exc).__name__}: {exc}",
            "tool_count": 0,
            "tools": [],
        }
    return {
        "status": "ok",
        "message": f"Discovered {len(tools)} tools.",
        "tool_count": len(tools),
        "tools": [
            {
                "name": str(tool.get("name") or "tool"),
                "description": str(tool.get("description") or ""),
            }
            for tool in tools
        ],
    }


def _required_config_id(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _optional_identifier(value: Any) -> str | None:
    text = str(value or "").strip()
    return _config_identifier(text, fallback="") if text else None


def _config_identifier(value: str, *, fallback: str) -> str:
    raw = value.strip() or fallback.strip()
    identifier = re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_")
    if not identifier:
        identifier = "item"
    if identifier[0].isdigit():
        identifier = f"item_{identifier}"
    return identifier[:64]


def _parse_args(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return shlex.split(text)


def _parse_env(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items() if str(key).strip()}
    env: dict[str, str] = {}
    for line in str(value or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, item = stripped.split("=", 1)
        key = key.strip()
        if key:
            env[key] = item.strip()
    return env


def _public_mcp_server(payload: dict[str, Any]) -> dict[str, Any]:
    server_id = str(payload.get("server_id") or "").strip()
    source = dict(payload.get("source") or {})
    enabled = payload.get("enabled", True) is not False
    env = payload.get("env") if isinstance(payload.get("env"), dict) else {}
    name = str(source.get("package") or source.get("name") or _humanize_identifier(server_id) or "MCP server")
    description = str(source.get("description") or source.get("summary") or "").strip()
    safe_payload = {
        "server_id": server_id,
        "display_name": name,
        "description": description,
        "transport": payload.get("transport"),
        "command": payload.get("command"),
        "args": list(payload.get("args") or []),
        "cwd": payload.get("cwd"),
        "source": source,
        "enabled": enabled,
        "required": bool(payload.get("required")),
        "tool_id_prefix": payload.get("tool_id_prefix"),
        "risk_level_default": payload.get("risk_level_default"),
        "timeout_seconds": payload.get("timeout_seconds"),
        "env_keys": sorted(str(key) for key in env),
    }
    return {
        "kind": "mcp",
        "name": name,
        "scope": str(source.get("type") or "local"),
        "status": "enabled" if enabled else "disabled",
        "enabled": enabled,
        "transport": payload.get("transport"),
        "summary": description or _mcp_server_summary(payload),
        "payload": safe_payload,
    }


def _public_skill(payload: dict[str, Any]) -> dict[str, Any]:
    skill_id = str(payload.get("skill_id") or "").strip()
    enabled = payload.get("enabled", True) is not False
    metadata = _skill_metadata_for_public_view(payload)
    name = metadata.get("name") or skill_id
    description = str(metadata.get("description") or "").strip()
    return {
        "kind": "skill",
        "name": _humanize_identifier(str(name)) or "Skill",
        "scope": str(payload.get("source") or "local"),
        "status": "enabled" if enabled else "disabled",
        "enabled": enabled,
        "summary": description or _skill_summary(payload),
        "payload": {
            "skill_id": skill_id,
            "description": description,
            "enabled": enabled,
            "source": payload.get("source"),
            "path": payload.get("path"),
            "required": bool(payload.get("required")),
            "resource_count": metadata.get("resource_count"),
            "script_count": metadata.get("script_count"),
        },
    }


def _mcp_server_summary(payload: dict[str, Any]) -> str:
    transport = str(payload.get("transport") or "unknown")
    command = str(payload.get("command") or "").strip()
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    package = str(source.get("package") or "").strip()
    if package:
        return f"{transport} connection from {package}"
    if command:
        return f"{transport} connection via {command}"
    return f"{transport} connection"


def _skill_summary(payload: dict[str, Any]) -> str:
    source = str(payload.get("source") or "local")
    path = str(payload.get("path") or "").strip()
    if path:
        return f"{source} skill at {path}"
    return f"{source} skill"


def _skill_metadata_for_public_view(payload: dict[str, Any]) -> dict[str, Any]:
    path = str(payload.get("path") or "").strip()
    if not path:
        return {}
    try:
        skill = parse_skill_directory(path)
    except Exception:
        return {}
    return {
        "name": skill.metadata.name,
        "description": skill.metadata.description,
        "resource_count": len(skill.resources),
        "script_count": len(skill.scripts),
    }


def _runtime_contract_path(runtime_root: Path, configured: str) -> Path:
    value = str(configured or "").strip()
    if not value:
        raise ValueError("runtime contract path must not be empty")
    if value == "/runtime":
        return runtime_root.resolve()
    if value.startswith("/runtime/"):
        return _root_relative_path(
            runtime_root,
            Path(value.removeprefix("/runtime/")),
            field_path="runtime contract path",
        )
    if value == ".agent_runtime":
        return runtime_root.resolve()
    if value.startswith(".agent_runtime/"):
        return _root_relative_path(
            runtime_root,
            Path(value.removeprefix(".agent_runtime/")),
            field_path="runtime contract path",
        )
    path = Path(value).expanduser()
    if path.is_absolute():
        raise ValueError(f"runtime contract path must resolve inside runtime workspace; got {value!r}")
    return _root_relative_path(runtime_root, path, field_path="runtime contract path")


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


def _humanize_identifier(value: str) -> str:
    text = re.sub(r"[_\\-]+", " ", str(value or "")).strip()
    return " ".join(part[:1].upper() + part[1:] for part in text.split())


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _write_json_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _path_updated_at(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    except OSError:
        return ""
