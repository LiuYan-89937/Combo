from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
from typing import Any


DEPENDENCY_POOL_ROOT_ENV = "AGENTFACTORY_DEPENDENCY_POOL_ROOT"
ENVIRONMENT_LOCK_PATH_ENV = "AGENTFACTORY_ENVIRONMENT_LOCK_PATH"
CONTAINER_DEPENDENCY_POOL_ROOT = "/dependency_pool"


class RuntimeDependencyError(RuntimeError):
    pass


def runtime_environment(lock: dict[str, Any], *, inherited: dict[str, str] | None = None) -> dict[str, str]:
    environment = dict(inherited or {})
    pool = _pool_payload(lock)
    python_paths = [
        str(PurePosixPath(CONTAINER_DEPENDENCY_POOL_ROOT) / _pool_relative(entry["path"]) / "site-packages")
        for entry in _entries(pool, "python_entries")
    ]
    npm_profile = pool.get("npm_profile")
    if isinstance(npm_profile, dict):
        npm_path = str(PurePosixPath(CONTAINER_DEPENDENCY_POOL_ROOT) / _pool_relative(_required_path(npm_profile)) / "node_modules")
        environment["NODE_PATH"] = _prepend_path(npm_path, environment.get("NODE_PATH"))
    if python_paths:
        environment["PYTHONPATH"] = _prepend_paths(python_paths, environment.get("PYTHONPATH"))
    environment[DEPENDENCY_POOL_ROOT_ENV] = CONTAINER_DEPENDENCY_POOL_ROOT
    environment[ENVIRONMENT_LOCK_PATH_ENV] = "/package/environment.lock.json"
    return environment


def activate_runtime_dependencies() -> dict[str, Any]:
    lock_path = Path(os.environ.get(ENVIRONMENT_LOCK_PATH_ENV, "/package/environment.lock.json"))
    pool_root = Path(os.environ.get(DEPENDENCY_POOL_ROOT_ENV, CONTAINER_DEPENDENCY_POOL_ROOT))
    lock = _read_lock(lock_path)
    pool = _pool_payload(lock)
    archives = [pool_root / _pool_relative(entry["path"]) for entry in _entries(pool, "system_entries")]
    requirements = lock.get("requirements") if isinstance(lock.get("requirements"), dict) else {}
    timeout_seconds = _timeout_seconds(requirements.get("install_timeout_seconds"))
    missing = [str(path) for path in archives if not path.is_file()]
    if missing:
        raise RuntimeDependencyError("dependency pool entries are missing: " + ", ".join(missing))
    if archives:
        _run_system_install(archives, timeout_seconds=timeout_seconds)
    binaries = requirements.get("system_binaries") if isinstance(requirements.get("system_binaries"), list) else []
    commands = requirements.get("verification_commands") if isinstance(requirements.get("verification_commands"), list) else []
    _verify_binaries([str(item) for item in binaries])
    _verify_commands(commands, timeout_seconds=timeout_seconds)
    return {
        "source": "dependency_pool",
        "python_entry_count": len(_entries(pool, "python_entries")),
        "system_entry_count": len(archives),
        "npm_profile": bool(pool.get("npm_profile")),
    }


def _run_system_install(archives: list[Path], *, timeout_seconds: int | None) -> None:
    command = [
        "apt-get",
        "install",
        "--no-download",
        "--no-install-recommends",
        "-y",
        *[str(path) for path in archives],
    ]
    environment = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False, env=environment)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeDependencyError(f"cached system dependency installation timed out after {timeout_seconds}s") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "cached system dependency installation failed").strip()
        raise RuntimeDependencyError(detail[-4000:])


def _verify_binaries(binaries: list[str]) -> None:
    missing = [binary for binary in binaries if binary and shutil.which(binary) is None]
    if missing:
        raise RuntimeDependencyError("declared system binaries are unavailable after dependency activation: " + ", ".join(missing))


def _verify_commands(commands: list[Any], *, timeout_seconds: int | None) -> None:
    for raw in commands:
        if not isinstance(raw, list) or not raw or not all(isinstance(item, str) and item for item in raw):
            raise RuntimeDependencyError("dependency verification commands must be non-empty string argument lists")
        if any(item in {"sh", "bash", "-c"} for item in raw):
            raise RuntimeDependencyError("dependency verification commands cannot use shell execution")
        try:
            completed = subprocess.run(raw, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeDependencyError(f"dependency verification timed out: {' '.join(raw)}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "verification failed").strip()
            raise RuntimeDependencyError(f"dependency verification failed: {' '.join(raw)}: {detail[-1000:]}")


def _read_lock(path: Path) -> dict[str, Any]:
    try:
        import json

        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeDependencyError(f"unable to read environment lock: {path}") from exc
    if not isinstance(value, dict) or value.get("version") != "environment_lock.v2":
        raise RuntimeDependencyError("environment lock is missing or incompatible")
    return value


def _pool_payload(lock: dict[str, Any]) -> dict[str, Any]:
    pool = lock.get("pool")
    if not isinstance(pool, dict) or pool.get("version") != "dependency_pool.v1":
        raise RuntimeDependencyError("environment lock does not contain a dependency pool reference")
    return pool


def _entries(pool: dict[str, Any], key: str) -> list[dict[str, str]]:
    value = pool.get(key)
    if not isinstance(value, list):
        raise RuntimeDependencyError(f"dependency pool field is invalid: {key}")
    entries: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise RuntimeDependencyError(f"dependency pool entry is invalid: {key}")
        path = _required_path(item)
        entries.append({"path": path})
    return entries


def _required_path(entry: dict[str, Any]) -> str:
    value = entry.get("path")
    if not isinstance(value, str) or not value:
        raise RuntimeDependencyError("dependency pool entry does not contain a path")
    _pool_relative(value)
    return value


def _pool_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeDependencyError(f"unsafe dependency pool path: {value}")
    return path


def _prepend_paths(prefixes: list[str], existing: str | None) -> str:
    return _prepend_path(":".join(prefixes), existing)


def _prepend_path(prefix: str, existing: str | None) -> str:
    return f"{prefix}:{existing}" if existing else prefix


def _timeout_seconds(value: object) -> int | None:
    return value if isinstance(value, int) and value > 0 else None
