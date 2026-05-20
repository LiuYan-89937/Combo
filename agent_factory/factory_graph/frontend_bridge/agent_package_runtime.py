from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any, Iterator
from uuid import uuid4

from agent_factory.runtime_contracts import AgentPackageLoader, LoadedAgentPackage
from agent_factory.runtime_kernel.session import AgentSessionConfig, AgentSessionManager
from agent_factory.runtime_kernel.extensions.loader import AgentInstanceExtensionConfigLoader
from agent_factory.mcp_gateway import HostMCPGatewayManager
from agent_factory.paths import factory_artifact_path, project_root
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent, event
from agent_factory.factory_graph.frontend_bridge.agent_runtime_launcher import (
    AgentRuntimeLaunchError,
    DockerAgentRuntimeLauncher,
)


DEFAULT_AGENT_PACKAGE_ROOT = ".agentfactory/packages"
DEFAULT_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS = 1800


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
        launcher: DockerAgentRuntimeLauncher | None = None,
    ) -> None:
        configured_root = package_root or os.getenv("AGENTFACTORY_PACKAGE_ROOT")
        self.package_root = Path(configured_root).expanduser() if configured_root else _default_package_root()
        self.loader = AgentPackageLoader()
        self.launcher = launcher or DockerAgentRuntimeLauncher()
        self.idle_timeout_seconds = _env_int(
            "AGENTFACTORY_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS",
            DEFAULT_AGENT_RUNTIME_IDLE_TIMEOUT_SECONDS,
        )
        self._containers: dict[str, AgentRuntimeContainerHandle] = {}
        self._mcp_gateways = HostMCPGatewayManager()

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
        target = self._package_dir(package_id)
        if not target.exists():
            raise FileNotFoundError(f"agent package not found: {package_id}")
        shutil.rmtree(target)
        return {"package_id": package_id, "deleted": True}

    def list_sessions(self, package_id: str) -> list[dict[str, Any]]:
        package = self.loader.load_path(self._manifest_path(package_id))
        return self._list_sessions_for_loaded_package(package)

    def run(self, package_id: str, *, user_input: str, session_id: str | None = None) -> AgentPackageRunResult:
        raise RuntimeError("AgentPackage host-process execution is disabled; use stream() for sandbox execution.")

    def stream(
        self,
        package_id: str,
        *,
        user_input: str,
        session_id: str | None = None,
        request_id: str | None = None,
    ) -> AgentPackageStreamRun:
        package = self.loader.load_path(self._manifest_path(package_id))
        command = {
            "type": "run_message",
            "request_id": request_id or uuid4().hex,
            "payload": {
                "message": user_input,
                "session_id": session_id,
            },
        }
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
            },
        }

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
                "extensions": _extensions_summary(package_id),
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
        self._mcp_gateways.close_all()

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
            yield "frontend_event", _node_event(
                request_id,
                "node_started",
                node_id="runtime_container",
                payload={"package_id": package_id, "status": "preflight"},
            )
        try:
            handle = self._container(package_id, package)
            if handle.startup_payload is not None:
                yield "frontend_event", _node_event(
                    request_id,
                    "node_completed",
                    node_id="runtime_container",
                    payload=handle.startup_payload,
                )
                handle.startup_payload = None
        except AgentRuntimeLaunchError as exc:
            if will_start:
                yield "frontend_event", _node_event(
                    request_id,
                    "node_failed",
                    node_id="runtime_container",
                    payload=exc.payload,
                    severity="error",
                )
            yield "frontend_event", _run_failed_event(request_id, exc.payload)
            return
        except Exception as exc:
            failure_payload = {
                "where": "agent_runtime.launch",
                "why": "container_start_failed",
                "message": f"{type(exc).__name__}: {exc}",
                "suggested_action": "Check Docker Desktop, runtime image, and sandbox contract.",
            }
            if will_start:
                yield "frontend_event", _node_event(
                    request_id,
                    "node_failed",
                    node_id="runtime_container",
                    payload=failure_payload,
                    severity="error",
                )
            yield "frontend_event", _run_failed_event(
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
        extension_root = runtime_root / "extensions"
        for path in (artifacts_root, workdir_root, runtime_root, extension_root):
            path.mkdir(parents=True, exist_ok=True)
        mcp_gateway = self._mcp_gateways.ensure_gateway(
            AgentInstanceExtensionConfigLoader(extension_root).load().mcp_servers
        )
        plan = self.launcher.prepare(
            package=package,
            runtime_root=runtime_root,
            artifacts_root=artifacts_root,
            workdir_root=workdir_root,
            mcp_gateway_url=mcp_gateway.docker_url if mcp_gateway is not None else None,
        )
        handle = AgentRuntimeContainerHandle(
            package_id=package_id,
            package_fingerprint=fingerprint,
            idle_timeout_seconds=self.idle_timeout_seconds,
            command=plan.command,
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

    def _has_reusable_container(self, package_id: str, package: LoadedAgentPackage) -> bool:
        existing = self._containers.get(package_id)
        if existing is None or not existing.is_running:
            return False
        if existing.package_fingerprint != _package_fingerprint(package):
            return False
        return not existing.is_idle(self.idle_timeout_seconds)

    def _close_container(self, package_id: str) -> None:
        handle = self._containers.pop(package_id, None)
        if handle is not None:
            handle.close()

    def _manifest_path(self, package_id: str) -> Path:
        return self._package_dir(package_id) / "agent_package.json"

    def _package_dir(self, package_id: str) -> Path:
        if not package_id or "/" in package_id or "\\" in package_id or package_id in {".", ".."}:
            raise ValueError(f"invalid agent package id: {package_id}")
        root = self.package_root.resolve()
        target = (root / package_id).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"agent package escapes package root: {package_id}") from exc
        return target


class AgentRuntimeContainerHandle:
    def __init__(
        self,
        *,
        package_id: str,
        package_fingerprint: str,
        idle_timeout_seconds: int,
        command: list[str],
    ) -> None:
        self.package_id = package_id
        self.package_fingerprint = package_fingerprint
        self.idle_timeout_seconds = idle_timeout_seconds
        self._idle_timer: threading.Timer | None = None
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.startup_payload: dict[str, Any] | None = None
        self.last_used = time.monotonic()
        self._schedule_idle_shutdown()

    @property
    def is_running(self) -> bool:
        return self.process.poll() is None

    def is_idle(self, timeout_seconds: int) -> bool:
        return timeout_seconds > 0 and (time.monotonic() - self.last_used) > timeout_seconds

    def send(self, command: dict[str, Any]) -> Iterator[tuple[str, Any]]:
        if not self.is_running:
            raise RuntimeError(f"agent runtime container for {self.package_id} is not running")
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("agent runtime container stdio is unavailable")
        request_id = str(command.get("request_id") or uuid4().hex)
        command["request_id"] = request_id
        self.process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        self.last_used = time.monotonic()
        self._cancel_idle_shutdown()
        for line in self.process.stdout:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                item = FactoryFrontendEvent.model_validate_json(stripped)
            except Exception:
                yield "stderr", stripped
                continue
            yield "frontend_event", item
            if item.request_id == request_id and item.event_type in {
                "run_completed",
                "run_failed",
                "tool_approval_requested",
                "interrupt_requested",
                "agent_package_sessions_listed",
                "error",
            }:
                self.last_used = time.monotonic()
                self._schedule_idle_shutdown()
                return
        return_code = self.process.wait()
        raise RuntimeError(f"agent runtime container exited with {return_code}")

    def close(self) -> None:
        self._cancel_idle_shutdown()
        if self.process.stdin is not None and self.is_running:
            try:
                self.process.stdin.write(json.dumps({"type": "shutdown", "request_id": uuid4().hex}) + "\n")
                self.process.stdin.flush()
            except Exception:
                pass
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

    def _schedule_idle_shutdown(self) -> None:
        self._cancel_idle_shutdown()
        if self.idle_timeout_seconds <= 0 or not self.is_running:
            return
        self._idle_timer = threading.Timer(self.idle_timeout_seconds, self.close)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _cancel_idle_shutdown(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None


def _host_runtime_root(package_id: str) -> Path:
    return factory_artifact_path("agent_runtime", package_id)


def _default_package_root() -> Path:
    return project_root() / DEFAULT_AGENT_PACKAGE_ROOT


def _default_project_root() -> Path:
    return project_root()


def _node_event(
    request_id: str,
    event_type: str,
    *,
    node_id: str,
    payload: dict[str, Any],
    severity: str | None = None,
) -> FactoryFrontendEvent:
    return event(
        event_type,  # type: ignore[arg-type]
        request_id=request_id,
        mode="agent_package",
        graph_id="agent_package_runtime",
        producer_type="agent_runtime_host",
        node_id=node_id,
        node_label="Runtime Container",
        node_kind="system",
        severity=severity,
        payload=payload,
    )


def _run_failed_event(request_id: str, payload: dict[str, Any]) -> FactoryFrontendEvent:
    return event(
        "run_failed",
        request_id=request_id,
        mode="agent_package",
        graph_id="agent_package_runtime",
        producer_type="agent_runtime_host",
        severity="error",
        message=str(payload.get("message") or "agent runtime launch failed"),
        payload=payload,
    )


def _package_fingerprint(package: LoadedAgentPackage) -> str:
    digest = hashlib.sha256()
    digest.update(str(package.package_root.resolve()).encode("utf-8"))
    _hash_tree(digest, package.package_root)
    _hash_tree(digest, _host_runtime_root(package.package_root.name) / "extensions")
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


def _extensions_summary(package_id: str) -> dict[str, str]:
    return {
        "host_root": str(_host_runtime_root(package_id) / "extensions"),
        "container_root": "/runtime/extensions",
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _path_updated_at(path: Path) -> str:
    from datetime import UTC, datetime

    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    except OSError:
        return ""
