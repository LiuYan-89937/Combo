from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import subprocess
from typing import Any

from agent_factory.paths import project_root
from agent_factory.model_pool import MODEL_POOL_STORE_PATH_ENV, ModelPoolStore, resolve_model_pool_store_path
from agent_factory.runtime_attachments import ATTACHMENT_INPUT_DIR
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

MODEL_ENV_ALLOWLIST: tuple[str, ...] = ()
CONTAINER_MODEL_POOL_STORE_PATH = "/runtime/model_pool/factory.sqlite"

SAFE_RESOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
ALLOWED_CONTAINER_ROOTS = (
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
        extension_root: Path | None = None,
        mcp_gateway_url: str | None = None,
        skillhub_gateway_url: str | None = None,
    ) -> DockerAgentRuntimePlan:
        docker = self._docker_executable()
        sandbox: dict[str, Any] = {}
        image = str(sandbox.get("image") or DEFAULT_RUNTIME_IMAGE)
        self._assert_daemon_available(docker)
        resolved_image = self._resolve_image_reference(docker, image)
        resources_path = package.package_root / package.manifest.resources_path
        if not resources_path.is_file():
            raise AgentRuntimeLaunchError(
                where="sandbox.mount.resources",
                why="resources_missing",
                message=f"AgentPackage resources file is missing: {resources_path}",
            )
        network = self._network_mode(sandbox)
        extension_root = extension_root or runtime_root / "extensions"
        extension_root.mkdir(parents=True, exist_ok=True)
        input_files_root = workdir_root / ATTACHMENT_INPUT_DIR
        input_files_root.mkdir(parents=True, exist_ok=True)
        service_env = self._service_environment(sandbox)
        model_pool_path = resolve_model_pool_store_path()
        ModelPoolStore(model_pool_path)
        env = {**self._environment(sandbox), **service_env}
        env[MODEL_POOL_STORE_PATH_ENV] = CONTAINER_MODEL_POOL_STORE_PATH
        if mcp_gateway_url:
            env["AGENTFACTORY_MCP_GATEWAY_URL"] = mcp_gateway_url
        if skillhub_gateway_url:
            env["AGENTFACTORY_SKILLHUB_GATEWAY_URL"] = skillhub_gateway_url
        command = [
            docker,
            "run",
            "--rm",
            "-i",
            "--network",
            network,
            "-v",
            f"{package.package_root.resolve()}:/package:ro",
            "-v",
            f"{resources_path.resolve()}:/resources/resources.json:ro",
            "-v",
            f"{artifacts_root.resolve()}:/artifacts:rw",
            "-v",
            f"{workdir_root.resolve()}:/workdir:rw",
            "-v",
            f"{input_files_root.resolve()}:/workdir/{ATTACHMENT_INPUT_DIR}:ro",
            "-v",
            f"{runtime_root.resolve()}:/runtime:rw",
            "-v",
            f"{extension_root.resolve()}:/runtime/extensions:rw",
            "-v",
            f"{model_pool_path.resolve()}:{CONTAINER_MODEL_POOL_STORE_PATH}:ro",
        ]
        contract_mounts = [*(sandbox.get("mounts") or []), *(sandbox.get("volumes") or [])]
        for mount in contract_mounts:
            mount_arg = self._mount_arg(mount)
            if mount_arg:
                command.extend(["-v", mount_arg])
        for key, value in env.items():
            command.extend(["-e", f"{key}={value}"])
        command.extend([resolved_image, "python", "-m", "agent_factory.agent_runtime_bridge.stdio_server"])
        return DockerAgentRuntimePlan(
            command=command,
            image=image,
            resolved_image=resolved_image,
            network=network,
            extension_root=extension_root,
            mount_count=6 + 2 + len(contract_mounts),
            service_env=service_env,
            preflight={
                "status": "ok",
                "docker": docker,
                "image": image,
                "resolved_image": resolved_image,
                "image_check": IMAGE_INSPECT_COMMAND_LABEL,
                "network": network,
                "extension_root": str(extension_root),
                "mount_count": 6 + 2 + len(contract_mounts),
                "service_env_keys": sorted(service_env),
                "mcp_gateway_url": mcp_gateway_url,
                "skillhub_gateway_url": skillhub_gateway_url,
            },
        )

    def build_command(
        self,
        *,
        package: LoadedAgentPackage,
        runtime_root: Path,
        artifacts_root: Path,
        workdir_root: Path,
        extension_root: Path | None = None,
        mcp_gateway_url: str | None = None,
        skillhub_gateway_url: str | None = None,
    ) -> list[str]:
        return self.prepare(
            package=package,
            runtime_root=runtime_root,
            artifacts_root=artifacts_root,
            workdir_root=workdir_root,
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

    def _resolve_image_reference(self, docker: str, image: str) -> str:
        try:
            result = subprocess.run(
                [docker, "image", "inspect", image],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentRuntimeLaunchError(
                where="docker.image_preflight",
                why="runtime_image_check_timeout",
                message=f"Docker runtime image preflight timed out: {image}",
                suggested_action=_runtime_image_build_suggestion(),
            ) from exc
        if result.returncode != 0:
            detail = _docker_error_text(result)
            resolved = self._image_id_from_exact_reference(docker, image)
            if resolved:
                return resolved
            why = "runtime_image_missing" if _looks_like_missing_image(detail) else "runtime_image_inspect_failed"
            suggested_action = (
                _runtime_image_build_suggestion()
                if why == "runtime_image_missing"
                else "Check Docker context, Docker socket permissions, and Docker Desktop status."
            )
            raise AgentRuntimeLaunchError(
                where="docker.image_preflight",
                why=why,
                message=f"Docker runtime image preflight failed for {image}: {detail or 'unknown docker error'}",
                suggested_action=suggested_action,
            )
        return image

    def _image_id_from_exact_reference(self, docker: str, image: str) -> str:
        try:
            result = subprocess.run(
                [
                    docker,
                    "image",
                    "ls",
                    "--filter",
                    f"reference={image}",
                    "--format",
                    "{{.ID}}",
                    "--no-trunc",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ""
        if result.returncode != 0:
            return ""
        ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(ids) != 1:
            return ""
        return ids[0]

    def _network_mode(self, sandbox: dict[str, Any]) -> str:
        policy = sandbox.get("network_policy") if isinstance(sandbox.get("network_policy"), dict) else {}
        mode = str(policy.get("mode") or "")
        if mode == "none":
            return "none"
        return "bridge"

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


def _looks_like_missing_image(value: str) -> bool:
    normalized = value.lower()
    return "no such image" in normalized or "no such object" in normalized or "not found" in normalized


def _runtime_image_build_suggestion() -> str:
    return f"{RUNTIME_IMAGE_BUILD_COMMAND} 或 {RUNTIME_IMAGE_MIRROR_BUILD_COMMAND}"
