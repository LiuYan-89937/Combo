from __future__ import annotations

from pathlib import Path

from agent_factory.paths import factory_artifact_path
from agent_factory.runtime_contracts import LoadedAgentPackage
from agent_factory.tooling.factory_extensions import default_system_agent_extension_root


def host_runtime_root(package_id: str) -> Path:
    return factory_artifact_path("agent_runtime", package_id)


def host_session_workdir(package_id: str, session_id: str) -> Path:
    normalized = str(session_id or "").strip()
    if not normalized:
        raise ValueError("agent package session_id is required for session workdir")
    return host_runtime_root(package_id) / "workdirs" / normalized


def host_scratch_workdir(package_id: str) -> Path:
    return host_runtime_root(package_id) / "_scratch" / "workdir"


def host_session_root(*, package_id: str, package: LoadedAgentPackage, configured: str) -> Path:
    value = configured.strip()
    runtime_root = host_runtime_root(package_id)
    if value == "/runtime":
        return runtime_root.resolve()
    if value.startswith("/runtime/"):
        return root_relative_path(
            runtime_root,
            Path(value.removeprefix("/runtime/")),
            field_path="session.config.session_root",
        )
    if value == ".agent_runtime":
        return runtime_root.resolve()
    if value.startswith(".agent_runtime/"):
        return root_relative_path(
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
    return root_relative_path(package.package_root, path, field_path="session.config.session_root")


def extension_root_for_package(package_id: str, package: LoadedAgentPackage) -> Path:
    if package_id == "factory_chat" and is_system_package(package):
        return default_system_agent_extension_root("factory_chat")
    if is_system_package(package):
        return package.package_root.parent / "extensions"
    return host_runtime_root(package_id) / "extensions"


def runtime_contract_path(runtime_root: Path, configured: str) -> Path:
    value = str(configured or "").strip()
    if not value:
        raise ValueError("runtime contract path must not be empty")
    if value == "/runtime":
        return runtime_root.resolve()
    if value.startswith("/runtime/"):
        return root_relative_path(
            runtime_root,
            Path(value.removeprefix("/runtime/")),
            field_path="runtime contract path",
        )
    if value == ".agent_runtime":
        return runtime_root.resolve()
    if value.startswith(".agent_runtime/"):
        return root_relative_path(
            runtime_root,
            Path(value.removeprefix(".agent_runtime/")),
            field_path="runtime contract path",
        )
    path = Path(value).expanduser()
    if path.is_absolute():
        raise ValueError(f"runtime contract path must resolve inside runtime workspace; got {value!r}")
    return root_relative_path(runtime_root, path, field_path="runtime contract path")


def root_relative_path(root_path: Path, path: Path, *, field_path: str) -> Path:
    root = root_path.resolve()
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field_path} must resolve inside its runtime workspace; got {str(path)!r}") from exc
    return target


def is_system_package(package: LoadedAgentPackage) -> bool:
    return bool(package.manifest.runtime.get("system_package"))


def is_host_system_package(package: LoadedAgentPackage) -> bool:
    if not is_system_package(package):
        return False
    backend = str(package.manifest.runtime.get("execution_backend") or "host").strip().lower()
    return backend == "host"
