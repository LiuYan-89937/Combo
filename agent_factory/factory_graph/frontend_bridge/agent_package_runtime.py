from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterator
from uuid import uuid4

from agent_factory.runtime_contracts import AgentPackageLoader, LoadedAgentPackage
from agent_factory.runtime_kernel.session import AgentSessionConfig, AgentSessionManager
from agent_factory.runtime_kernel.extensions.loader import AgentInstanceExtensionConfigLoader
from agent_factory.mcp_gateway import HostMCPGatewayManager
from agent_factory.package_runtime import host_runtime_package_view
from agent_factory.package_runtime.request_lifecycle import RuntimeRequestPolicy
from agent_factory.paths import factory_artifact_path, project_root
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.factory_graph.frontend_bridge.agent_runtime_launcher import (
    AgentRuntimeLaunchError,
    DockerAgentRuntimeLauncher,
)
from agent_factory.factory_graph.frontend_bridge.container_runtime_handle import AgentRuntimeContainerHandle
from agent_factory.factory_graph.frontend_bridge.runtime_events import node_event, run_failed_event
from agent_factory.factory_graph.frontend_bridge.system_package_runtime_handle import SystemPackageRuntimeHandle


DEFAULT_AGENT_PACKAGE_ROOT = ".agentfactory/packages"
DEFAULT_SYSTEM_PACKAGE_ROOT = "SystemPackage"
DEFAULT_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS = 1800
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
        self._mcp_gateways = HostMCPGatewayManager()
        self._emit = emit

    def set_emit(self, emit: Emit | None) -> None:
        self._emit = emit
        for handle in self._containers.values():
            handle.set_emit(emit)
        for handle in self._system_handles.values():
            handle.set_emit(emit)

    def list_packages(self) -> list[dict[str, Any]]:
        self.package_root.mkdir(parents=True, exist_ok=True)
        packages: list[dict[str, Any]] = []
        for manifest_path in sorted(self.package_root.glob("*/agent_package.json")):
            packages.append(self._package_summary(manifest_path))
        return sorted(packages, key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    def package_summary(self, package_id: str) -> dict[str, Any]:
        return self._package_summary(self._manifest_path(package_id))

    def delete_package(self, package_id: str) -> dict[str, Any]:
        self._close_container(package_id)
        target = self._package_dir(package_id, include_system_packages=False)
        if not target.exists():
            raise FileNotFoundError(f"agent package not found: {package_id}")
        shutil.rmtree(target)
        return {"package_id": package_id, "deleted": True}

    def list_sessions(self, package_id: str) -> list[dict[str, Any]]:
        package = self.loader.load_path(self._manifest_path(package_id))
        return self._list_sessions_for_loaded_package(package)

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
    ) -> AgentPackageStreamRun:
        package = self.loader.load_path(self._manifest_path(package_id))
        command = {
            "type": "run_message",
            "request_id": request_id or uuid4().hex,
            "payload": {
                "message": user_input,
                "session_id": session_id,
                "user_config": dict(user_config or {}),
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
            }

    def _session_manager_for_package(self, package_id: str, package: LoadedAgentPackage) -> AgentSessionManager:
        session_contract = package.contracts.get("session") if isinstance(package.contracts, dict) else None
        config = session_contract.get("config", {}) if isinstance(session_contract, dict) else {}
        root = _host_runtime_root(package_id) / "sessions"
        if isinstance(config, dict):
            configured = str(config.get("session_root") or "")
            if configured and not configured.startswith("/runtime"):
                root = Path(configured)
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
        yield from handle.send(command)

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
            yield from handle.send(command)
        except Exception:
            self._close_container(package_id)
            raise

    def _container(self, package_id: str, package: LoadedAgentPackage) -> "AgentRuntimeContainerHandle":
        existing = self._containers.get(package_id)
        fingerprint = _package_fingerprint(package)
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
        _seed_package_extensions(package=package, extension_root=extension_root)
        fingerprint = _package_fingerprint(package)
        mcp_gateway = self._mcp_gateways.ensure_gateway(
            AgentInstanceExtensionConfigLoader(extension_root).load().mcp_servers
        )
        plan = self.launcher.prepare(
            package=package,
            runtime_root=runtime_root,
            artifacts_root=artifacts_root,
            workdir_root=workdir_root,
            extension_root=extension_root,
            mcp_gateway_url=mcp_gateway.docker_url if mcp_gateway is not None else None,
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
        fingerprint = _package_fingerprint(package)
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
        self._system_handles[package_id] = handle
        return handle

    def _has_reusable_container(self, package_id: str, package: LoadedAgentPackage) -> bool:
        existing = self._containers.get(package_id)
        if existing is None or not existing.is_running:
            return False
        if existing.package_fingerprint != _package_fingerprint(package):
            return False
        return not existing.is_idle(self.idle_timeout_seconds)

    def _has_reusable_system_handle(self, package_id: str, package: LoadedAgentPackage) -> bool:
        existing = self._system_handles.get(package_id)
        if existing is None:
            return False
        if existing.package_fingerprint != _package_fingerprint(package):
            return False
        return not existing.is_idle(self.idle_timeout_seconds)

    def _close_container(self, package_id: str) -> None:
        handle = self._containers.pop(package_id, None)
        if handle is not None:
            handle.close()

    def _close_system(self, package_id: str) -> None:
        handle = self._system_handles.pop(package_id, None)
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


def _host_runtime_root(package_id: str) -> Path:
    return factory_artifact_path("agent_runtime", package_id)


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


def _package_fingerprint(package: LoadedAgentPackage) -> str:
    digest = hashlib.sha256()
    digest.update(str(package.package_root.resolve()).encode("utf-8"))
    _hash_tree(digest, package.package_root)
    _hash_tree(digest, _extension_root_for_package(package.package_root.name, package))
    if _is_host_system_package(package):
        digest.update(b"host-system-package")
    else:
        digest.update(_runtime_image_identity(package).encode("utf-8"))
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


def _extension_root_for_package(package_id: str, package: LoadedAgentPackage) -> Path:
    if _is_system_package(package):
        return package.package_root.parent / "extensions"
    return _host_runtime_root(package_id) / "extensions"


def _seed_package_extensions(*, package: LoadedAgentPackage, extension_root: Path) -> None:
    package_extensions = package.package_root / "extensions"
    if not package_extensions.is_dir():
        return
    extension_root.mkdir(parents=True, exist_ok=True)
    _merge_extension_config(
        source_path=package_extensions / "mcp_servers.json",
        target_path=extension_root / "mcp_servers.json",
        list_key="servers",
        id_key="server_id",
        default_version="mcp_servers.v0",
    )
    _merge_extension_config(
        source_path=package_extensions / "enabled_skills.json",
        target_path=extension_root / "enabled_skills.json",
        list_key="skills",
        id_key="skill_id",
        default_version="enabled_skills.v0",
    )
    source_skills = package_extensions / "skills"
    if source_skills.is_dir():
        target_skills = extension_root / "skills"
        target_skills.mkdir(parents=True, exist_ok=True)
        for source_skill in sorted(item for item in source_skills.iterdir() if item.is_dir()):
            target_skill = target_skills / source_skill.name
            if target_skill.exists():
                continue
            shutil.copytree(source_skill, target_skill)


def _merge_extension_config(
    *,
    source_path: Path,
    target_path: Path,
    list_key: str,
    id_key: str,
    default_version: str,
) -> None:
    source_payload = _read_json_object(source_path)
    source_items = source_payload.get(list_key)
    if not isinstance(source_items, list) or not source_items:
        return
    target_payload = _read_json_object(target_path)
    target_items = target_payload.get(list_key)
    if not isinstance(target_items, list):
        target_items = []
    existing = {
        str(item.get(id_key) or "")
        for item in target_items
        if isinstance(item, dict) and str(item.get(id_key) or "")
    }
    merged = list(target_items)
    for item in source_items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get(id_key) or "")
        if not item_id or item_id in existing:
            continue
        merged.append(item)
        existing.add(item_id)
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
    host_root = _extension_root_for_package(package_id, package) if package is not None else _host_runtime_root(package_id) / "extensions"
    return {
        "host_root": str(host_root),
        "container_root": "/runtime/extensions",
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _path_updated_at(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    except OSError:
        return ""
