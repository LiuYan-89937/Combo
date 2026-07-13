from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_factory.agent_runtime_bridge.dependencies import load_dependencies_contract
from agent_factory.paths import factory_artifact_path


class EnvironmentResolutionError(RuntimeError):
    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


class EnvironmentResolver:
    def ensure(self, package_root: str | Path) -> dict[str, Any]:
        root = Path(package_root).expanduser().resolve()
        contract = load_dependencies_contract(root)
        config = contract.config
        if not contract.enabled or config.install_mode == "none":
            return self._write_lock(root, self._base_lock(config.base_image, status="ready"))
        docker = shutil.which("docker")
        if not docker:
            raise EnvironmentResolutionError("docker_unavailable", "Docker CLI is required to resolve package environment")
        architecture = _docker_architecture(docker)
        allowed = set(config.platform_architectures)
        if allowed and architecture not in allowed:
            raise EnvironmentResolutionError(
                "platform_mismatch",
                f"package requires architectures {sorted(allowed)}, current Docker architecture is {architecture}",
            )
        base_image = str(config.base_image or "agentfactory-runtime-python:3.12").strip()
        base_digest = _image_identity(docker, base_image)
        payload = {
            "base_image": base_image,
            "base_digest": base_digest,
            "architecture": architecture,
            "system_packages": sorted(set(config.system_packages)),
            "python_requirements": sorted(set(config.python_requirements)),
            "npm_requirements": sorted(set(config.npm_requirements)),
            "system_binaries": sorted(set(config.system_binaries)),
            "verification_commands": config.verification_commands,
        }
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        image = f"agentfactory-env:{fingerprint[:24]}"
        existing = _inspect_image(docker, image)
        if not existing:
            self._build(docker, image=image, payload=payload, timeout_seconds=config.install_timeout_seconds)
        self._verify(docker, image=image, binaries=payload["system_binaries"], commands=payload["verification_commands"])
        return self._write_lock(
            root,
            {
                "version": "environment_lock.v1",
                "status": "ready",
                "fingerprint": fingerprint,
                "image": image,
                "image_digest": _image_identity(docker, image),
                "platform": {"os": "linux", "architecture": architecture},
                "requirements": payload,
                "verified_at": _now(),
            },
        )

    def read_lock(self, package_root: str | Path) -> dict[str, Any]:
        path = environment_lock_path(package_root)
        if not path.is_file():
            raise EnvironmentResolutionError("environment_lock_missing", f"package environment lock is missing: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("status") != "ready" or not value.get("image"):
            raise EnvironmentResolutionError("environment_lock_invalid", f"package environment lock is not ready: {path}")
        return value

    def _build(self, docker: str, *, image: str, payload: dict[str, Any], timeout_seconds: int | None) -> None:
        build_root = factory_artifact_path("environment_images", "builds", image.replace(":", "-"))
        build_root.mkdir(parents=True, exist_ok=True)
        dockerfile = build_root / "Dockerfile"
        dockerfile.write_text(_dockerfile(payload), encoding="utf-8")
        try:
            completed = subprocess.run(
                [docker, "build", "--network", "host", "-t", image, "-f", str(dockerfile), str(build_root)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise EnvironmentResolutionError("build_failed", f"environment image build timed out after {timeout_seconds}s") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "Docker build failed").strip()
            raise EnvironmentResolutionError("build_failed", detail[-4000:])

    def _verify(self, docker: str, *, image: str, binaries: list[str], commands: list[list[str]]) -> None:
        checks = [["command", "-v", binary] for binary in binaries if binary]
        checks.extend(command for command in commands if command)
        for command in checks:
            if any(item in {"sh", "bash", "-c"} for item in command):
                raise EnvironmentResolutionError("unsupported", "verification commands must be direct executable arguments")
            completed = subprocess.run([docker, "run", "--rm", image, *command], capture_output=True, text=True, timeout=30, check=False)
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "verification failed").strip()
                raise EnvironmentResolutionError("build_failed", f"environment verification failed: {' '.join(command)}: {detail[-1000:]}")

    def _base_lock(self, image: str, *, status: str) -> dict[str, Any]:
        return {
            "version": "environment_lock.v1",
            "status": status,
            "fingerprint": "base",
            "image": image,
            "image_digest": "",
            "platform": {"os": "linux", "architecture": ""},
            "requirements": {},
            "verified_at": _now(),
        }

    def _write_lock(self, package_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
        path = environment_lock_path(package_root)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        return payload


def environment_lock_path(package_root: str | Path) -> Path:
    return Path(package_root).expanduser().resolve() / "environment.lock.json"


def _docker_architecture(docker: str) -> str:
    completed = subprocess.run([docker, "version", "--format", "{{.Server.Arch}}"], capture_output=True, text=True, timeout=10, check=False)
    if completed.returncode != 0:
        raise EnvironmentResolutionError("docker_unavailable", (completed.stderr or "Docker daemon is unavailable").strip())
    value = completed.stdout.strip().lower()
    return {"aarch64": "arm64", "x86_64": "amd64"}.get(value, value)


def _inspect_image(docker: str, image: str) -> bool:
    return subprocess.run([docker, "image", "inspect", image], capture_output=True, text=True, timeout=10, check=False).returncode == 0


def _image_identity(docker: str, image: str) -> str:
    completed = subprocess.run([docker, "image", "inspect", image, "--format", "{{.Id}}"], capture_output=True, text=True, timeout=10, check=False)
    if completed.returncode != 0:
        raise EnvironmentResolutionError("runtime_image_missing", (completed.stderr or f"image is unavailable: {image}").strip())
    return completed.stdout.strip()


def _dockerfile(payload: dict[str, Any]) -> str:
    lines = [f"FROM {payload['base_image']}"]
    packages = payload["system_packages"]
    if packages:
        lines.append("RUN apt-get update && apt-get install -y --no-install-recommends " + " ".join(packages) + " && rm -rf /var/lib/apt/lists/*")
    requirements = payload["python_requirements"]
    if requirements:
        lines.append("RUN python -m pip install --no-cache-dir " + " ".join(requirements))
    npm_requirements = payload["npm_requirements"]
    if npm_requirements:
        lines.append("RUN npm install --global " + " ".join(npm_requirements))
    return "\n".join(lines) + "\n"


def _now() -> str:
    return datetime.now(UTC).isoformat()
