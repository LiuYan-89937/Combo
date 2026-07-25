from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_factory.agent_runtime_bridge.dependencies import load_dependencies_contract

from .pool import DependencyPool, DependencyPoolError, DependencyPoolResolution
from .python_requirements import PythonRequirementError, normalize_python_requirements
from .runtime_image import (
    RuntimeImageResolutionError,
    configured_runtime_image_id,
    resolve_runtime_image,
)
from .versions import DEPENDENCY_POOL_VERSION, ENVIRONMENT_LOCK_VERSION


EnvironmentProgress = Callable[[str, dict[str, Any]], None]


class EnvironmentResolutionError(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


class EnvironmentResolver:
    """Resolves AgentPackage dependency declarations into shared-pool references."""

    def __init__(self, pool: DependencyPool | None = None) -> None:
        self.pool = pool or DependencyPool()

    def ensure(
        self,
        package_root: str | Path,
        *,
        on_progress: EnvironmentProgress | None = None,
        verify_runtime_image: bool = False,
    ) -> dict[str, Any]:
        root = Path(package_root).expanduser().resolve()
        _notify(on_progress, "checking_contract", package_root=str(root))
        contract = load_dependencies_contract(root)
        config = contract.config
        base_image = str(config.base_image or "agentfactory-runtime-python:3.12").strip()
        if not _has_materializable_dependencies(enabled=contract.enabled, config=config):
            base_digest = self._base_image_identity(
                base_image,
                verify_runtime_image=verify_runtime_image,
            )
            request = _dependency_request(
                enabled=contract.enabled,
                base_image=base_image,
                base_digest=base_digest,
                architecture="",
                config=config,
            )
            request_fingerprint = _fingerprint(request)
            existing = self._read_lock_payload(root)
            if self._is_reusable_lock(existing, request_fingerprint):
                _notify(on_progress, "ready", cache_status="lock_hit", dependency_count=0)
                return existing
            result = self._write_lock(
                root,
                {
                    "version": ENVIRONMENT_LOCK_VERSION,
                    "status": "ready",
                    "request_fingerprint": request_fingerprint,
                    "image": base_image,
                    "image_digest": base_digest,
                    "platform": {"os": "linux", "architecture": ""},
                    "requirements": request,
                    "pool": DependencyPoolResolution([], [], None).to_lock_payload(),
                    "verified_at": _now(),
                },
            )
            _notify(on_progress, "ready", cache_status="lock_created", dependency_count=0)
            return result
        docker = shutil.which("docker")
        if not docker:
            raise EnvironmentResolutionError("docker_unavailable", "Docker CLI is required to resolve package dependencies")
        _notify(on_progress, "checking_runtime", base_image=base_image)
        architecture = _docker_architecture(docker)
        allowed = set(config.platform_architectures)
        if allowed and architecture not in allowed:
            raise EnvironmentResolutionError(
                "platform_mismatch",
                f"package requires architectures {sorted(allowed)}, current Docker architecture is {architecture}",
            )
        base_image = str(config.base_image or "agentfactory-runtime-python:3.12").strip()
        try:
            base_digest = resolve_runtime_image(
                docker,
                base_image,
                pinned_image=base_image if verify_runtime_image else None,
            ).resolved
        except RuntimeImageResolutionError as exc:
            raise EnvironmentResolutionError(exc.status, str(exc)) from exc
        request = _dependency_request(
            enabled=contract.enabled,
            base_image=base_image,
            base_digest=base_digest,
            architecture=architecture,
            config=config,
        )
        request_fingerprint = _fingerprint(request)
        existing = self._read_lock_payload(root)
        if self._is_reusable_lock(existing, request_fingerprint):
            _notify(
                on_progress,
                "ready",
                cache_status="lock_hit",
                dependency_count=_dependency_count(request),
            )
            return existing
        _notify(
            on_progress,
            "resolving_dependencies",
            cache_status="resolving_profile",
            dependency_count=_dependency_count(request),
        )
        try:
            resolution = self.pool.resolve(
                docker=docker,
                base_image=base_digest,
                architecture=architecture,
                python_requirements=request["python_requirements"],
                system_packages=request["system_packages"],
                npm_requirements=request["npm_requirements"],
                timeout_seconds=config.install_timeout_seconds,
            )
        except DependencyPoolError as exc:
            raise EnvironmentResolutionError(exc.status, str(exc)) from exc
        _notify(
            on_progress,
            "dependency_profile_ready",
            cache_status=resolution.cache_status,
            profile_key=resolution.profile_key,
            python_artifact_count=len(resolution.python_entries),
            system_artifact_count=len(resolution.system_entries),
            npm_profile_ready=resolution.npm_profile is not None,
        )
        payload = {
            "version": ENVIRONMENT_LOCK_VERSION,
            "status": "ready",
            "request_fingerprint": request_fingerprint,
            "image": base_image,
            "image_digest": base_digest,
            "platform": {"os": "linux", "architecture": architecture},
            "requirements": request,
            "pool": resolution.to_lock_payload(),
            "verified_at": _now(),
        }
        result = self._write_lock(root, payload)
        _notify(
            on_progress,
            "ready",
            cache_status="pool_ready",
            dependency_count=_dependency_count(request),
        )
        return result

    @staticmethod
    def _base_image_identity(
        base_image: str,
        *,
        verify_runtime_image: bool,
    ) -> str:
        if not verify_runtime_image:
            return configured_runtime_image_id(base_image) or ""
        docker = shutil.which("docker")
        if not docker:
            raise EnvironmentResolutionError(
                "docker_unavailable",
                "Docker CLI is required to verify the Agent runtime image",
            )
        try:
            return resolve_runtime_image(
                docker,
                base_image,
                pinned_image=base_image,
            ).resolved
        except RuntimeImageResolutionError as exc:
            raise EnvironmentResolutionError(exc.status, str(exc)) from exc

    def read_lock(self, package_root: str | Path) -> dict[str, Any]:
        root = Path(package_root).expanduser().resolve()
        value = self._read_lock_payload(root)
        if not self._is_ready_lock(value):
            raise EnvironmentResolutionError(
                "environment_lock_invalid",
                f"package environment lock is missing or incompatible: {environment_lock_path(root)}",
            )
        return value

    def _is_reusable_lock(self, value: dict[str, Any] | None, request_fingerprint: str) -> bool:
        return bool(
            self._is_ready_lock(value)
            and value.get("request_fingerprint") == request_fingerprint
            and self.pool.references_available(value.get("pool"))
        )

    def _is_ready_lock(self, value: dict[str, Any] | None) -> bool:
        return bool(
            isinstance(value, dict)
            and value.get("version") == ENVIRONMENT_LOCK_VERSION
            and value.get("status") == "ready"
            and isinstance(value.get("image"), str)
            and value["image"]
            and isinstance(value.get("pool"), dict)
            and value["pool"].get("version") == DEPENDENCY_POOL_VERSION
            and self.pool.references_available(value["pool"])
        )

    def _read_lock_payload(self, package_root: Path) -> dict[str, Any] | None:
        path = environment_lock_path(package_root)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None

    def _write_lock(self, package_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
        path = environment_lock_path(package_root)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        return payload


def environment_lock_path(package_root: str | Path) -> Path:
    return Path(package_root).expanduser().resolve() / "environment.lock.json"


def _dependency_request(
    *,
    enabled: bool,
    base_image: str,
    base_digest: str,
    architecture: str,
    config: Any,
) -> dict[str, Any]:
    try:
        python_requirements = normalize_python_requirements(config.python_requirements) if enabled else []
    except PythonRequirementError as exc:
        raise EnvironmentResolutionError("dependency_declaration_invalid", str(exc)) from exc
    return {
        "enabled": bool(enabled),
        "base_image": base_image,
        "base_digest": base_digest,
        "architecture": architecture,
        "python_requirements": python_requirements,
        "system_packages": _normalized_values(config.system_packages) if enabled else [],
        "npm_requirements": _normalized_values(config.npm_requirements) if enabled else [],
        "system_binaries": _normalized_values(config.system_binaries) if enabled else [],
        "verification_commands": config.verification_commands if enabled else [],
        "install_timeout_seconds": config.install_timeout_seconds,
    }


def _normalized_values(values: list[str]) -> list[str]:
    return sorted({value.strip() for value in values if value and value.strip()})


def _has_materializable_dependencies(*, enabled: bool, config: Any) -> bool:
    return bool(enabled and (config.python_requirements or config.system_packages or config.npm_requirements))


def _dependency_count(request: dict[str, Any]) -> int:
    return sum(
        len(request.get(key) or [])
        for key in ("python_requirements", "system_packages", "npm_requirements")
    )


def _notify(callback: EnvironmentProgress | None, stage: str, **payload: Any) -> None:
    if callback is not None:
        callback(stage, payload)


def _fingerprint(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _docker_architecture(docker: str) -> str:
    completed = subprocess.run(
        [docker, "version", "--format", "{{.Server.Arch}}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if completed.returncode != 0:
        raise EnvironmentResolutionError("docker_unavailable", (completed.stderr or "Docker daemon is unavailable").strip())
    value = completed.stdout.strip().lower()
    return {"aarch64": "arm64", "x86_64": "amd64"}.get(value, value)


def _now() -> str:
    return datetime.now(UTC).isoformat()
