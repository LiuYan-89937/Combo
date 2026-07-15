from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import threading
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from agent_factory.agent_runtime_bridge.paths import (
    BRIDGE_ARTIFACTS_ROOT_ENV,
    BRIDGE_EXTENSION_ROOT_ENV,
    BRIDGE_PACKAGE_ROOT_ENV,
    BRIDGE_RUNTIME_ROOT_ENV,
    BRIDGE_RUNTIME_INSTANCE_ID_ENV,
    BRIDGE_WORKDIR_ROOT_ENV,
)
from agent_factory.model_pool import (
    MODEL_POOL_STORE_PATH_ENV,
    MODEL_POOL_STORE_READ_ONLY_ENV,
    ModelPoolStore,
    resolve_model_pool_store_path,
)
from agent_factory.paths import factory_artifact_path, project_root
from agent_factory.runtime_attachments import ATTACHMENT_INPUT_DIR
from agent_factory.environment_system import (
    EnvironmentResolver,
    RuntimeImageResolutionError,
    dependency_pool_path,
    resolve_runtime_image,
)
from agent_factory.environment_system.runtime import (
    CONTAINER_DEPENDENCY_POOL_ROOT,
    ENVIRONMENT_LOCK_PATH_ENV,
    runtime_environment,
)
from agent_factory.resource_system import ResourceStore
from agent_factory.resource_system.store import RESOURCE_MASTER_KEY_ENV, RESOURCE_STORE_PATH_ENV, RESOURCE_STORE_READ_ONLY_ENV
from agent_factory.runtime_contracts import LoadedAgentPackage


DEFAULT_RUNTIME_IMAGE = "agentfactory-runtime-python:3.12"
RUNTIME_IMAGE_BUILD_COMMAND = (
    "docker build -t agentfactory-runtime-python:3.12 -f docker/agent-runtime/Dockerfile ."
)
RUNTIME_IMAGE_MIRROR_BUILD_COMMAND = (
    "docker build -t agentfactory-runtime-python:3.12 "
    "--build-arg PYTHON_BASE_IMAGE=<python-3.12-slim-mirror> "
    "-f docker/agent-runtime/Dockerfile ."
)
IMAGE_INSPECT_COMMAND_LABEL = "docker image inspect"

MODEL_ENV_ALLOWLIST: tuple[str, ...] = (
    "AGENTFACTORY_LOCAL_INFERENCE_ENDPOINT",
    "AGENTFACTORY_LOCAL_INFERENCE_ALLOWED_HOSTS",
    "AGENTFACTORY_LOCAL_INFERENCE_TIMEOUT_SECONDS",
    "AGENTFACTORY_LOCAL_EMBEDDING_ENDPOINT",
    "AGENTFACTORY_LOCAL_EMBEDDING_ALLOWED_HOSTS",
    "AGENTFACTORY_LOCAL_EMBEDDING_TIMEOUT_SECONDS",
)
CONTAINER_ENDPOINT_ENV_PAIRS: tuple[tuple[str, str], ...] = (
    ("AGENTFACTORY_LOCAL_INFERENCE_ENDPOINT", "AGENTFACTORY_LOCAL_INFERENCE_ALLOWED_HOSTS"),
    ("AGENTFACTORY_LOCAL_EMBEDDING_ENDPOINT", "AGENTFACTORY_LOCAL_EMBEDDING_ALLOWED_HOSTS"),
)
CONTAINER_HOST_ALIAS = "host.docker.internal"
LOOPBACK_ENDPOINT_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
CONTAINER_MODEL_POOL_STORE_PATH = "/runtime/control_plane/model_pool.sqlite"
CONTAINER_COLLABORATION_ROOT = "/collaboration"
CONTAINER_RESOURCE_STORE_PATH = "/runtime/control_plane/resources.sqlite"
SHARED_PROJECT_ROOT = PurePosixPath("/agentfactory/project")
CONTAINER_ISOLATION_ENV = "AGENTFACTORY_CONTAINER_ISOLATION"
CONTAINER_INCOMPATIBLE_POLICY_ENV = "AGENTFACTORY_CONTAINER_INCOMPATIBLE_POLICY"
SAFE_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
ALLOWED_CONTAINER_ROOTS = (
    PurePosixPath(CONTAINER_DEPENDENCY_POOL_ROOT),
    PurePosixPath("/resources"),
    PurePosixPath("/package"),
    PurePosixPath("/artifacts"),
    PurePosixPath("/workdir"),
    PurePosixPath("/runtime"),
)


@dataclass(frozen=True, slots=True)
class DockerAgentRuntimePlan:
    command: list[str]
    image: str
    resolved_image: str
    network: str
    extension_root: Path
    mount_count: int
    service_env: dict[str, str]
    preflight: dict[str, Any]
    isolation: str = "dedicated"
    shared_container_id: str | None = None

    def command_for_python_module(self, module: str) -> list[str]:
        if self.command[-3:-1] != ["python", "-m"]:
            raise ValueError("runtime command does not end with a Python module entrypoint")
        return [*self.command[:-3], "python", "-m", module]


class AgentRuntimeLaunchError(RuntimeError):
    def __init__(self, *, where: str, why: str, message: str, suggested_action: str | None = None) -> None:
        super().__init__(message)
        self.payload = {
            "where": where,
            "why": why,
            "message": message,
            "suggested_action": suggested_action,
        }


class DockerAgentRuntimeLauncher:
    def prepare(
        self,
        *,
        package: LoadedAgentPackage,
        runtime_root: Path,
        artifacts_root: Path,
        workdir_root: Path,
        runtime_instance_id: str,
        extension_root: Path | None = None,
        mcp_gateway_url: str | None = None,
        skillhub_gateway_url: str | None = None,
    ) -> DockerAgentRuntimePlan:
        runtime_instance_id = str(runtime_instance_id or "").strip()
        if not runtime_instance_id:
            raise AgentRuntimeLaunchError(
                where="docker.runtime_instance",
                why="runtime_instance_id_missing",
                message="Docker Agent runtime requires a stable runtime instance identifier.",
            )
        docker = self._docker_executable()
        sandbox: dict[str, Any] = {}
        environment_lock = EnvironmentResolver().read_lock(package.package_root)
        image = str(environment_lock["image"])
        self._assert_daemon_available(docker)
        pinned_image = str(environment_lock.get("image_digest") or "").strip() or None
        try:
            resolved_image = resolve_runtime_image(docker, image, pinned_image=pinned_image).resolved
        except RuntimeImageResolutionError as exc:
            suggested_action = (
                _runtime_image_build_suggestion()
                if exc.status == "runtime_image_missing"
                else "Check Docker context, Docker socket permissions, and Docker Desktop status."
            )
            raise AgentRuntimeLaunchError(
                where="docker.image_preflight",
                why=exc.status,
                message=f"Docker runtime image preflight failed for {pinned_image or image}: {exc}",
                suggested_action=suggested_action,
            ) from exc
        network = self._network_mode(sandbox)
        extension_root = extension_root or runtime_root / "extensions"
        extension_root = self._prepare_runtime_extension_root(
            source_extension_root=extension_root,
            runtime_root=runtime_root,
        )
        _assert_package_runtime_workspace(
            runtime_root=runtime_root,
            artifacts_root=artifacts_root,
            workdir_root=workdir_root,
            extension_root=extension_root,
        )
        input_files_root = workdir_root / ATTACHMENT_INPUT_DIR
        input_files_root.mkdir(parents=True, exist_ok=True)
        service_env = self._service_environment(sandbox)
        model_pool_path = resolve_model_pool_store_path()
        ModelPoolStore(model_pool_path)
        resource_store = ResourceStore()
        control_plane_root = runtime_root / "control_plane"
        model_pool_snapshot = control_plane_root / "model_pool.sqlite"
        resource_store_snapshot = control_plane_root / "resources.sqlite"
        _refresh_sqlite_snapshot(model_pool_path, model_pool_snapshot)
        _refresh_sqlite_snapshot(resource_store.path, resource_store_snapshot)
        collaboration_root = factory_artifact_path("collaboration")
        collaboration_root.mkdir(parents=True, exist_ok=True)
        dependency_pool = dependency_pool_path()
        dependency_pool.mkdir(parents=True, exist_ok=True)
        env = runtime_environment(
            environment_lock,
            inherited={**self._environment(sandbox), **service_env},
        )
        env[MODEL_POOL_STORE_PATH_ENV] = CONTAINER_MODEL_POOL_STORE_PATH
        env[MODEL_POOL_STORE_READ_ONLY_ENV] = "1"
        env[BRIDGE_RUNTIME_INSTANCE_ID_ENV] = runtime_instance_id
        env["AGENTFACTORY_COLLABORATION_ROOT"] = CONTAINER_COLLABORATION_ROOT
        env[RESOURCE_STORE_PATH_ENV] = CONTAINER_RESOURCE_STORE_PATH
        env[RESOURCE_STORE_READ_ONLY_ENV] = "1"
        if resource_store.key_available:
            env[RESOURCE_MASTER_KEY_ENV] = os.environ[RESOURCE_MASTER_KEY_ENV]
        if mcp_gateway_url:
            env["AGENTFACTORY_MCP_GATEWAY_URL"] = mcp_gateway_url
        if skillhub_gateway_url:
            env["AGENTFACTORY_SKILLHUB_GATEWAY_URL"] = skillhub_gateway_url
        contract_mounts = [*(sandbox.get("mounts") or []), *(sandbox.get("volumes") or [])]
        logical_fallback_reason: str | None = None
        requested_isolation = _container_isolation(package)
        if requested_isolation == "logical":
            if contract_mounts:
                logical_fallback_reason = "package declares container-specific mounts"
            else:
                try:
                    return self._prepare_logical_plan(
                        docker=docker,
                        package=package,
                        runtime_root=runtime_root,
                        artifacts_root=artifacts_root,
                        workdir_root=workdir_root,
                        extension_root=extension_root,
                        environment_lock=environment_lock,
                        image=image,
                        resolved_image=resolved_image,
                        network=network,
                        env=env,
                        service_env=service_env,
                        model_pool_path=model_pool_snapshot,
                        collaboration_root=collaboration_root,
                        resource_store_path=resource_store_snapshot,
                        dependency_pool=dependency_pool,
                        mcp_gateway_url=mcp_gateway_url,
                        skillhub_gateway_url=skillhub_gateway_url,
                    )
                except _SharedRuntimeIncompatible as exc:
                    logical_fallback_reason = str(exc)
            if logical_fallback_reason and _incompatible_container_policy() == "error":
                raise AgentRuntimeLaunchError(
                    where="docker.logical_isolation",
                    why="shared_runtime_incompatible",
                    message=logical_fallback_reason,
                    suggested_action=(
                        f"Set {CONTAINER_ISOLATION_ENV}=dedicated or align the package runtime image and mounts."
                    ),
                )
        command = [
            docker,
            "run",
            "--rm",
            "-i",
            "--network",
            network,
            "--add-host",
            f"{CONTAINER_HOST_ALIAS}:host-gateway",
        ]
        mounts = [
            f"{package.package_root.resolve()}:/package:ro",
            f"{artifacts_root.resolve()}:/artifacts:rw",
            f"{workdir_root.resolve()}:/workdir:rw",
            f"{runtime_root.resolve()}:/runtime:rw",
            f"{collaboration_root.resolve()}:{CONTAINER_COLLABORATION_ROOT}:rw",
            f"{dependency_pool}:{CONTAINER_DEPENDENCY_POOL_ROOT}:ro",
        ]
        try:
            workdir_alias = runtime_container_path(workdir_root)
        except ValueError:
            workdir_alias = None
        if workdir_alias is not None:
            mounts.append(f"{workdir_root.resolve()}:{workdir_alias}:rw")
        for mount in contract_mounts:
            mount_arg = self._mount_arg(mount)
            if mount_arg:
                mounts.append(mount_arg)
        for mount in mounts:
            command.extend(["-v", mount])
        for key, value in env.items():
            command.extend(["-e", f"{key}={value}"])
        command.extend([resolved_image, "python", "-m", "agent_factory.agent_runtime_bridge.stdio_server"])
        return DockerAgentRuntimePlan(
            command=command,
            image=image,
            resolved_image=resolved_image,
            network=network,
            extension_root=extension_root,
            mount_count=len(mounts),
            service_env=service_env,
            preflight={
                "status": "ok",
                "docker": docker,
                "image": image,
                "environment_lock": environment_lock,
                "resolved_image": resolved_image,
                "image_check": IMAGE_INSPECT_COMMAND_LABEL,
                "network": network,
                "extension_root": str(extension_root),
                "mount_count": len(mounts),
                "dependency_pool": str(dependency_pool),
                "service_env_keys": sorted(service_env),
                "mcp_gateway_url": mcp_gateway_url,
                "skillhub_gateway_url": skillhub_gateway_url,
                "isolation": "dedicated",
                "runtime_instance_id": runtime_instance_id,
                "requested_isolation": requested_isolation,
                "logical_fallback_reason": logical_fallback_reason,
            },
            isolation="dedicated",
        )

    def _prepare_logical_plan(
        self,
        *,
        docker: str,
        package: LoadedAgentPackage,
        runtime_root: Path,
        artifacts_root: Path,
        workdir_root: Path,
        extension_root: Path,
        environment_lock: dict[str, Any],
        image: str,
        resolved_image: str,
        network: str,
        env: dict[str, str],
        service_env: dict[str, str],
        model_pool_path: Path,
        collaboration_root: Path,
        resource_store_path: Path,
        dependency_pool: Path,
        mcp_gateway_url: str | None,
        skillhub_gateway_url: str | None,
    ) -> DockerAgentRuntimePlan:
        try:
            container_paths = {
                "package": runtime_container_path(package.package_root),
                "runtime": runtime_container_path(runtime_root),
                "artifacts": runtime_container_path(artifacts_root),
                "workdir": runtime_container_path(workdir_root),
                "extension": runtime_container_path(extension_root),
                "model_pool": runtime_container_path(model_pool_path),
                "collaboration": runtime_container_path(collaboration_root),
                "resource_store": runtime_container_path(resource_store_path),
            }
        except ValueError as exc:
            raise _SharedRuntimeIncompatible(str(exc)) from exc
        runtime_parent = factory_artifact_path("agent_runtime")
        runtime_parent.mkdir(parents=True, exist_ok=True)
        shared = _SHARED_RUNTIME.ensure(
            docker=docker,
            image=image,
            resolved_image=resolved_image,
            network=network,
            runtime_parent=runtime_parent,
            collaboration_root=collaboration_root,
            dependency_pool=dependency_pool,
        )
        logical_env = dict(env)
        logical_env.update(
            {
                ENVIRONMENT_LOCK_PATH_ENV: str(container_paths["package"] / "environment.lock.json"),
                MODEL_POOL_STORE_PATH_ENV: str(container_paths["model_pool"]),
                "AGENTFACTORY_COLLABORATION_ROOT": str(container_paths["collaboration"]),
                RESOURCE_STORE_PATH_ENV: str(container_paths["resource_store"]),
                BRIDGE_PACKAGE_ROOT_ENV: str(container_paths["package"]),
                BRIDGE_ARTIFACTS_ROOT_ENV: str(container_paths["artifacts"]),
                BRIDGE_RUNTIME_ROOT_ENV: str(container_paths["runtime"]),
                BRIDGE_WORKDIR_ROOT_ENV: str(container_paths["workdir"]),
                BRIDGE_EXTENSION_ROOT_ENV: str(container_paths["extension"]),
            }
        )
        command = [docker, "exec", "-i", "-w", str(container_paths["workdir"])]
        for key, value in logical_env.items():
            command.extend(["-e", f"{key}={value}"])
        command.extend([shared.container_id, "python", "-m", "agent_factory.agent_runtime_bridge.stdio_server"])
        return DockerAgentRuntimePlan(
            command=command,
            image=image,
            resolved_image=resolved_image,
            network=network,
            extension_root=extension_root,
            mount_count=shared.mount_count,
            service_env=service_env,
            preflight={
                "status": "ok",
                "docker": docker,
                "image": image,
                "environment_lock": environment_lock,
                "resolved_image": resolved_image,
                "image_check": IMAGE_INSPECT_COMMAND_LABEL,
                "network": network,
                "extension_root": str(extension_root),
                "mount_count": shared.mount_count,
                "dependency_pool": str(dependency_pool),
                "service_env_keys": sorted(service_env),
                "mcp_gateway_url": mcp_gateway_url,
                "skillhub_gateway_url": skillhub_gateway_url,
                "isolation": "logical",
                "runtime_instance_id": logical_env[BRIDGE_RUNTIME_INSTANCE_ID_ENV],
                "shared_container_id": shared.container_id,
                "context_paths": {key: str(value) for key, value in container_paths.items()},
                "environment_lock_path": logical_env[ENVIRONMENT_LOCK_PATH_ENV],
            },
            isolation="logical",
            shared_container_id=shared.container_id,
        )

    def _prepare_runtime_extension_root(self, *, source_extension_root: Path, runtime_root: Path) -> Path:
        runtime_extension_root = runtime_root / "extensions"
        source = source_extension_root.expanduser().resolve()
        target = runtime_extension_root.resolve()
        if source == target:
            target.mkdir(parents=True, exist_ok=True)
            return target
        if source.exists():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            target.mkdir(parents=True, exist_ok=True)
        return target

    def build_command(
        self,
        *,
        package: LoadedAgentPackage,
        runtime_root: Path,
        artifacts_root: Path,
        workdir_root: Path,
        runtime_instance_id: str,
        extension_root: Path | None = None,
        mcp_gateway_url: str | None = None,
        skillhub_gateway_url: str | None = None,
    ) -> list[str]:
        return self.prepare(
            package=package,
            runtime_root=runtime_root,
            artifacts_root=artifacts_root,
            workdir_root=workdir_root,
            runtime_instance_id=runtime_instance_id,
            extension_root=extension_root,
            mcp_gateway_url=mcp_gateway_url,
            skillhub_gateway_url=skillhub_gateway_url,
        ).command

    def _docker_executable(self) -> str:
        docker = shutil.which("docker")
        if docker is None:
            raise AgentRuntimeLaunchError(
                where="docker.preflight",
                why="docker_cli_missing",
                message="Docker executable was not found.",
                suggested_action="Install Docker Desktop and make sure the docker command is on PATH.",
            )
        return docker

    def _assert_daemon_available(self, docker: str) -> None:
        try:
            result = subprocess.run(
                [docker, "info", "--format", "{{json .ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentRuntimeLaunchError(
                where="docker.preflight",
                why="docker_daemon_timeout",
                message="Docker daemon preflight timed out.",
                suggested_action="Start Docker Desktop and retry.",
            ) from exc
        if result.returncode != 0:
            raise AgentRuntimeLaunchError(
                where="docker.preflight",
                why="docker_daemon_unavailable",
                message=(result.stderr or result.stdout or "Docker daemon is not available.").strip(),
                suggested_action="Start Docker Desktop and retry.",
            )

    def _network_mode(self, sandbox: dict[str, Any]) -> str:
        policy = sandbox.get("network_policy") if isinstance(sandbox.get("network_policy"), dict) else {}
        mode = str(policy.get("mode") or "")
        if mode == "none":
            return "none"
        return "host"

    def _environment(self, sandbox: dict[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        sandbox_env = sandbox.get("env") if isinstance(sandbox.get("env"), dict) else {}
        for key, value in sandbox_env.items():
            if key:
                result[str(key)] = str(value)
        for key in MODEL_ENV_ALLOWLIST:
            value = os.getenv(key)
            if value:
                result[key] = value
        for item in sandbox.get("secrets") or []:
            if not isinstance(item, dict):
                continue
            env_key = str(item.get("target_env") or item.get("env") or item.get("env_name") or "").strip()
            if not env_key:
                continue
            value = os.getenv(env_key)
            if value is None:
                raise AgentRuntimeLaunchError(
                    where="sandbox.secrets",
                    why="secret_env_missing",
                    message=f"Required secret environment variable is missing: {env_key}",
                    suggested_action=f"Set {env_key} in the host environment before starting this AgentPackage.",
                )
            result[env_key] = value
        _rewrite_container_endpoints(result)
        return result

    def _service_environment(self, sandbox: dict[str, Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        services = sandbox.get("services") if isinstance(sandbox.get("services"), list) else []
        for item in services:
            if not isinstance(item, dict):
                continue
            service_id = str(item.get("service_id") or item.get("id") or "").strip()
            endpoint = str(item.get("endpoint") or "").strip()
            if not service_id or not endpoint:
                continue
            result[f"AGENT_SERVICE_{_env_key_fragment(service_id)}_ENDPOINT"] = endpoint
        return result

    def _mount_arg(self, mount: object) -> str | None:
        if not isinstance(mount, dict):
            return None
        validated = self._validate_contract_mount(mount)
        access = "ro" if validated.access == "read_only" else "rw"
        return f"{validated.host_path}:{validated.container_path}:{access}"

    def _validate_contract_mount(self, mount: dict[str, Any]) -> "_ValidatedContractMount":
        host_path = str(mount.get("host_path") or "").strip()
        container_path = str(mount.get("container_path") or "").strip()
        if not host_path or not container_path:
            raise AgentRuntimeLaunchError(
                where="sandbox.mounts",
                why="invalid_mount",
                message="Sandbox mount requires host_path and container_path.",
            )
        resource_id = str(mount.get("resource_id") or "").strip()
        self._validate_resource_id(resource_id, required=False)
        normalized_container_path = self._validate_container_path(
            container_path,
            resource_id=resource_id or None,
        )
        host = Path(host_path).expanduser().resolve()
        self._validate_host_path(host)
        access_value = str(mount.get("access") or "read_write")
        if access_value not in {"read_only", "read_write"}:
            raise AgentRuntimeLaunchError(
                where="sandbox.mounts",
                why="invalid_mount_access",
                message=f"Sandbox mount access must be read_only or read_write: {access_value}",
            )
        return _ValidatedContractMount(
            host_path=host,
            container_path=str(normalized_container_path),
            access=access_value,
        )

    def _validate_host_path(self, host: Path) -> None:
        if not host.exists():
            raise AgentRuntimeLaunchError(
                where="sandbox.mounts",
                why="host_path_missing",
                message=f"Sandbox mount host path does not exist: {host}",
            )
        dangerous_paths = _dangerous_host_paths()
        if host in dangerous_paths:
            raise AgentRuntimeLaunchError(
                where="sandbox.mounts",
                why="dangerous_host_path",
                message=f"Sandbox mount host path is not allowed: {host}",
            )

    def _validate_container_path(self, container_path: str, *, resource_id: str | None) -> PurePosixPath:
        if not container_path.startswith("/"):
            raise AgentRuntimeLaunchError(
                where="sandbox.mounts",
                why="invalid_container_path",
                message=f"Sandbox container path must be absolute: {container_path}",
            )
        path = PurePosixPath(container_path)
        if ".." in path.parts:
            raise AgentRuntimeLaunchError(
                where="sandbox.mounts",
                why="invalid_container_path",
                message=f"Sandbox container path cannot contain '..': {container_path}",
            )
        if path == PurePosixPath("/"):
            raise AgentRuntimeLaunchError(
                where="sandbox.mounts",
                why="invalid_container_path",
                message="Sandbox container path cannot be root.",
            )
        if _is_volumes_path(path):
            path_resource_id = _volume_resource_id(path)
            self._validate_resource_id(path_resource_id, required=True)
            if resource_id and path_resource_id != resource_id:
                raise AgentRuntimeLaunchError(
                    where="sandbox.mounts",
                    why="resource_id_container_path_mismatch",
                    message=(
                        "Sandbox mount resource_id must match /volumes/<resource_id>: "
                        f"{resource_id} != {path_resource_id}"
                    ),
                )
            return path
        if not _is_allowed_container_path(path):
            raise AgentRuntimeLaunchError(
                where="sandbox.mounts",
                why="disallowed_container_path",
                message=f"Sandbox container path is outside allowed runtime roots: {container_path}",
            )
        if not resource_id:
            raise AgentRuntimeLaunchError(
                where="sandbox.mounts",
                why="missing_resource_id",
                message=(
                    "Sandbox contract mounts outside /volumes/<resource_id> must declare resource_id. "
                    f"container_path={container_path}"
                ),
            )
        return path

    def _validate_resource_id(self, resource_id: str | None, *, required: bool) -> None:
        if not resource_id:
            if required:
                raise AgentRuntimeLaunchError(
                    where="sandbox.mounts",
                    why="missing_resource_id",
                    message="Sandbox mount requires a safe resource_id.",
                )
            return
        if not SAFE_RESOURCE_ID_RE.fullmatch(resource_id):
            raise AgentRuntimeLaunchError(
                where="sandbox.mounts",
                why="invalid_resource_id",
                message=f"Sandbox mount resource_id contains unsupported characters: {resource_id}",
            )


@dataclass(frozen=True, slots=True)
class _ValidatedContractMount:
    host_path: Path
    container_path: str
    access: str


def _env_key_fragment(value: str) -> str:
    chars = [char.upper() if char.isalnum() else "_" for char in value]
    result = "".join(chars).strip("_") or "SERVICE"
    if result[0].isdigit():
        result = f"SERVICE_{result}"
    return result


def _dangerous_host_paths() -> set[Path]:
    candidates = [
        Path("/"),
        Path.home(),
        project_root(),
        Path("/Users"),
    ]
    return {candidate.expanduser().resolve() for candidate in candidates}


def _is_allowed_container_path(path: PurePosixPath) -> bool:
    return any(path == root or root in path.parents for root in ALLOWED_CONTAINER_ROOTS)


def _is_volumes_path(path: PurePosixPath) -> bool:
    return len(path.parts) >= 3 and path.parts[0] == "/" and path.parts[1] == "volumes"


def _volume_resource_id(path: PurePosixPath) -> str:
    if not _is_volumes_path(path):
        return ""
    return path.parts[2]


def _docker_error_text(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()


@dataclass(frozen=True, slots=True)
class SharedRuntimeLease:
    container_id: str
    mount_count: int


class _SharedRuntimeIncompatible(RuntimeError):
    pass


def _refresh_sqlite_snapshot(source: Path, target: Path) -> None:
    """Create an atomic, transactionally consistent runtime read snapshot."""

    source_path = source.expanduser().resolve()
    target_path = target.expanduser().resolve()
    if not source_path.is_file():
        raise AgentRuntimeLaunchError(
            where="docker.control_plane_snapshot",
            why="source_database_missing",
            message=f"Runtime control-plane database is not initialized: {source_path}",
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = target_path.with_suffix(target_path.suffix + ".tmp")
    temporary_path.unlink(missing_ok=True)
    try:
        with sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True) as source_conn:
            with sqlite3.connect(temporary_path) as target_conn:
                source_conn.backup(target_conn)
        temporary_path.replace(target_path)
    except Exception as exc:
        temporary_path.unlink(missing_ok=True)
        raise AgentRuntimeLaunchError(
            where="docker.control_plane_snapshot",
            why="snapshot_failed",
            message=f"Failed to snapshot runtime control-plane database {source_path}: {exc}",
        ) from exc


def _assert_package_runtime_workspace(
    *,
    runtime_root: Path,
    artifacts_root: Path,
    workdir_root: Path,
    extension_root: Path,
) -> None:
    root = runtime_root.resolve()
    for field_name, path in (
        ("artifacts_root", artifacts_root),
        ("workdir_root", workdir_root),
        ("extension_root", extension_root),
    ):
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise AgentRuntimeLaunchError(
                where="docker.runtime_workspace",
                why="writable_path_outside_package_runtime",
                message=(
                    f"{field_name} must resolve inside the package runtime workspace: "
                    f"root={root}, path={resolved}"
                ),
            ) from exc


class _SharedDockerRuntime:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._container_id: str | None = None
        self._docker: str | None = None
        self._resolved_image: str | None = None
        self._network: str | None = None
        self._mount_count = 0

    def ensure(
        self,
        *,
        docker: str,
        image: str,
        resolved_image: str,
        network: str,
        runtime_parent: Path,
        collaboration_root: Path,
        dependency_pool: Path,
    ) -> SharedRuntimeLease:
        with self._lock:
            if self._container_id and self._is_running(docker, self._container_id):
                if self._resolved_image != resolved_image:
                    raise _SharedRuntimeIncompatible(
                        f"shared runtime image is {self._resolved_image}, requested package image is {resolved_image}"
                    )
                if self._network != network:
                    raise _SharedRuntimeIncompatible(
                        f"shared runtime network is {self._network}, requested package network is {network}"
                    )
                return SharedRuntimeLease(self._container_id, self._mount_count)
            self._reset()
            project = project_root().resolve()
            runtime_mount = runtime_container_path(runtime_parent)
            collaboration_mount = runtime_container_path(collaboration_root)
            command = [
                docker,
                "run",
                "--rm",
                "-d",
                "--network",
                network,
                "--add-host",
                f"{CONTAINER_HOST_ALIAS}:host-gateway",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--label",
                "agentfactory.runtime.isolation=logical",
                "-v",
                f"{project}:{SHARED_PROJECT_ROOT}:ro",
                "-v",
                f"{runtime_parent.resolve()}:{runtime_mount}:rw",
                "-v",
                f"{collaboration_root.resolve()}:{collaboration_mount}:rw",
                "-v",
                f"{dependency_pool.resolve()}:{CONTAINER_DEPENDENCY_POOL_ROOT}:ro",
                resolved_image,
                "python",
                "-m",
                "agent_factory.agent_runtime_bridge.container_keeper",
            ]
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
            except Exception as exc:
                raise AgentRuntimeLaunchError(
                    where="docker.shared_runtime",
                    why="shared_container_start_failed",
                    message=f"Failed to start shared runtime container from {image}: {type(exc).__name__}: {exc}",
                ) from exc
            container_id = result.stdout.strip()
            if result.returncode != 0 or not container_id:
                raise AgentRuntimeLaunchError(
                    where="docker.shared_runtime",
                    why="shared_container_start_failed",
                    message=_docker_error_text(result) or f"Failed to start shared runtime container from {image}",
                )
            if not self._is_running(docker, container_id):
                raise AgentRuntimeLaunchError(
                    where="docker.shared_runtime",
                    why="shared_container_exited",
                    message=f"Shared runtime container exited immediately after starting from {image}",
                    suggested_action=RUNTIME_IMAGE_BUILD_COMMAND,
                )
            self._container_id = container_id
            self._docker = docker
            self._resolved_image = resolved_image
            self._network = network
            self._mount_count = 4
            return SharedRuntimeLease(container_id, self._mount_count)

    def close(self) -> None:
        with self._lock:
            container_id = self._container_id
            docker = self._docker
            self._reset()
        if not container_id or not docker:
            return
        try:
            subprocess.run(
                [docker, "stop", "--time", "5", container_id],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return

    def _is_running(self, docker: str, container_id: str) -> bool:
        try:
            result = subprocess.run(
                [docker, "container", "inspect", container_id, "--format", "{{.State.Running}}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            return False
        return result.returncode == 0 and result.stdout.strip().lower() == "true"

    def _reset(self) -> None:
        self._container_id = None
        self._docker = None
        self._resolved_image = None
        self._network = None
        self._mount_count = 0


def runtime_container_path(path: str | Path) -> PurePosixPath:
    host = Path(path).expanduser().resolve()
    root = project_root().resolve()
    try:
        relative = host.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"logical runtime path is outside the shared project root: {host}") from exc
    return SHARED_PROJECT_ROOT.joinpath(*relative.parts)


def _rewrite_container_endpoints(environment: dict[str, str]) -> None:
    for endpoint_key, allowed_hosts_key in CONTAINER_ENDPOINT_ENV_PAIRS:
        endpoint = environment.get(endpoint_key)
        if not endpoint:
            continue
        rewritten = _container_endpoint(endpoint)
        if rewritten == endpoint:
            continue
        environment[endpoint_key] = rewritten
        allowed_hosts = [
            item.strip()
            for item in environment.get(allowed_hosts_key, "").split(",")
            if item.strip()
        ]
        if CONTAINER_HOST_ALIAS not in {item.lower() for item in allowed_hosts}:
            allowed_hosts.append(CONTAINER_HOST_ALIAS)
        environment[allowed_hosts_key] = ",".join(allowed_hosts)


def _container_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if (parsed.hostname or "").lower() not in LOOPBACK_ENDPOINT_HOSTS:
        return endpoint
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit(
        (parsed.scheme, f"{CONTAINER_HOST_ALIAS}{port}", parsed.path, parsed.query, parsed.fragment)
    )


def shutdown_shared_runtime() -> None:
    _SHARED_RUNTIME.close()


def _container_isolation(package: LoadedAgentPackage) -> str:
    runtime = package.manifest.runtime if isinstance(package.manifest.runtime, dict) else {}
    value = str(runtime.get("container_isolation") or os.getenv(CONTAINER_ISOLATION_ENV) or "logical").strip().lower()
    return value if value in {"logical", "dedicated"} else "logical"


def _incompatible_container_policy() -> str:
    value = str(os.getenv(CONTAINER_INCOMPATIBLE_POLICY_ENV) or "dedicated").strip().lower()
    return value if value in {"dedicated", "error"} else "dedicated"


_SHARED_RUNTIME = _SharedDockerRuntime()


def _runtime_image_build_suggestion() -> str:
    return f"{RUNTIME_IMAGE_BUILD_COMMAND} 或 {RUNTIME_IMAGE_MIRROR_BUILD_COMMAND}"
