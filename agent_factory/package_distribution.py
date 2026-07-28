from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import tempfile
from typing import Any, Iterable
import zipfile

from agent_factory.create_agent.package_paths import (
    is_transient_package_path,
    normalize_package_relative,
)
from agent_factory.tooling.providers import EnabledSkillsConfig, MCPServersConfig


PACKAGE_ASSET_DIRS = frozenset(
    {
        "artifacts",
        "extensions",
        "formatters",
        "knowledge",
        "patterns",
        "policies",
        "prompts",
        "resources",
        "strategies",
        "tools",
    }
)
PACKAGE_REPORT_FILENAME = "package_report.json"
DISTRIBUTION_LOCAL_PARTS = frozenset({".agent_runtime", ".factory", "checkpoints", "logs", "sessions"})
DISTRIBUTION_LOCAL_NAMES = frozenset({".env", "agent.sqlite", "runtime.sqlite"})
DISTRIBUTION_LOCAL_SUFFIXES = frozenset({".log", ".pyc", ".pyo"})
TEXT_SUFFIXES = frozenset(
    {
        ".cjs",
        ".ini",
        ".js",
        ".json",
        ".md",
        ".mjs",
        ".ps1",
        ".py",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }
)
SECRET_PATTERNS = (
    ("aliyun_access_key", re.compile(r"\bLTAI[A-Za-z0-9]{12,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "authorization_header",
        re.compile(r"(?i)\bauthorization\s*[:=]\s*['\"]?(?:bearer|basic)\s+[^\s'\"]{8,}"),
    ),
    (
        "credential_assignment",
        re.compile(
            r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
            r"\s*[:=]\s*['\"][^'\"]{8,}"
        ),
    ),
    (
        "credential_query_parameter",
        re.compile(
            r"(?i)[?&](?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
            r"=[^&\s'\"]{8,}"
        ),
    ),
)
HOST_PATH_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_])/(?:Users|home|root|private/(?:tmp|var)|var/folders|tmp)/[^\s\"']+"),
    re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:\\[^\s\"']+"),
)
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|auth(?:orization)?|client[_-]?secret|"
    r"password|private[_-]?key|secret)"
)


class PackageDistributionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PackageDistributionPolicy:
    publishable_files: frozenset[str]
    publishable_dirs: frozenset[str]

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> "PackageDistributionPolicy":
        files = {"agent_package.json", "environment.lock.json"}
        dirs: set[str] = set()
        _add_manifest_file(files, manifest.get("assembly_spec_path"))
        contracts = manifest.get("contracts")
        if isinstance(contracts, dict):
            for value in contracts.values():
                _add_manifest_file(files, value)
        for key in (
            "bindings",
            "patterns",
            "prompts",
            "tools",
            "policies",
            "strategies",
            "formatters",
        ):
            value = manifest.get(key)
            items = value if isinstance(value, list) else value.values() if isinstance(value, dict) else ()
            for item in items:
                _add_manifest_file(files, item)
                _add_asset_dir_for_manifest_path(dirs, item)
        return cls(
            publishable_files=frozenset(files),
            publishable_dirs=frozenset(dirs | set(PACKAGE_ASSET_DIRS)),
        )

    def allows(self, relative_path: str) -> bool:
        normalized = normalize_package_relative(relative_path)
        if (
            normalized == PACKAGE_REPORT_FILENAME
            or is_transient_package_path(normalized)
            or _is_distribution_local_path(normalized)
        ):
            return False
        if normalized in self.publishable_files:
            return True
        return any(
            normalized == directory or normalized.startswith(f"{directory}/")
            for directory in self.publishable_dirs
        )


def copy_publishable_package(source: Path, target: Path) -> None:
    policy = PackageDistributionPolicy.from_manifest(read_manifest_payload(source))
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(item for item in source.rglob("*") if item.is_file()):
        if path.is_symlink():
            continue
        relative = path.relative_to(source).as_posix()
        if not policy.allows(relative):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def export_distribution_archive(source: Path, package_id: str, archive_path: Path) -> None:
    manifest = read_manifest_payload(source)
    manifest_agent = manifest.get("agent")
    manifest_package_id = (
        str(manifest_agent.get("id") or "").strip()
        if isinstance(manifest_agent, dict)
        else ""
    )
    if manifest_package_id != package_id:
        raise PackageDistributionError(
            f"package id {package_id!r} does not match manifest id {manifest_package_id!r}"
        )
    with tempfile.TemporaryDirectory(prefix="agent-package-distribution-") as temp_dir:
        snapshot_root = Path(temp_dir) / source.name
        copy_publishable_package(source, snapshot_root)
        _sanitize_distribution_snapshot(source=source, snapshot=snapshot_root)
        validate_distribution_snapshot(snapshot_root)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(item for item in snapshot_root.rglob("*") if item.is_file()):
                relative = Path(source.name) / path.relative_to(snapshot_root)
                archive.write(path, relative.as_posix())


def read_manifest_payload(root: Path) -> dict[str, Any]:
    path = root / "agent_package.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PackageDistributionError("agent_package.json must be readable before distribution") from exc
    if not isinstance(payload, dict):
        raise PackageDistributionError("agent_package.json must contain a JSON object")
    return payload


def validate_distribution_snapshot(root: Path) -> None:
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise PackageDistributionError(f"symbolic links are not distributable: {relative}")
        if (
            is_transient_package_path(relative)
            or _is_distribution_local_path(relative)
            or relative == PACKAGE_REPORT_FILENAME
        ):
            raise PackageDistributionError(f"runtime or local-only file is not distributable: {relative}")
        if path.suffix.casefold() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise PackageDistributionError(f"text file is not valid UTF-8: {relative}") from exc
        for kind, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                raise PackageDistributionError(
                    f"distribution blocked because {kind} was detected in {relative}"
                )
        for pattern in HOST_PATH_PATTERNS:
            if pattern.search(text):
                raise PackageDistributionError(
                    f"distribution blocked because a host absolute path remains in {relative}"
                )
        for value in _walk_json_strings(path, text):
            if _host_absolute_path(value):
                raise PackageDistributionError(
                    f"distribution blocked because a host absolute path remains in {relative}"
                )
        for key, value in _walk_json_items(path, text):
            if SENSITIVE_KEY_PATTERN.search(key) and _looks_like_secret_value(value):
                raise PackageDistributionError(
                    f"distribution blocked because a credential value remains in {relative}"
                )


def _sanitize_distribution_snapshot(*, source: Path, snapshot: Path) -> None:
    _sanitize_mcp_config(source=source, snapshot=snapshot)
    _sanitize_enabled_skills(source=source, snapshot=snapshot)
    _sanitize_resource_defaults(snapshot)


def _sanitize_mcp_config(*, source: Path, snapshot: Path) -> None:
    source_path = source / "extensions" / "mcp_servers.json"
    snapshot_path = snapshot / "extensions" / "mcp_servers.json"
    if not snapshot_path.is_file():
        return
    config = MCPServersConfig.model_validate_json(source_path.read_text(encoding="utf-8"))
    servers = []
    for server in config.servers:
        env_keys = sorted(server.env)
        header_keys = sorted(server.headers)
        removed_cwd = bool(server.cwd)
        source_metadata = _without_host_paths(dict(server.source))
        needs_configuration = bool(env_keys or header_keys or removed_cwd)
        if needs_configuration:
            source_metadata["distribution"] = {
                "requires_configuration": True,
                "env_keys": env_keys,
                "header_keys": header_keys,
                "cwd_required": removed_cwd,
            }
        servers.append(
            server.model_copy(
                update={
                    "cwd": None,
                    "env": {},
                    "headers": {},
                    "source": source_metadata,
                    "enabled": False if needs_configuration else server.enabled,
                }
            )
        )
    snapshot_path.write_text(
        config.model_copy(update={"servers": servers}).model_dump_json(indent=2),
        encoding="utf-8",
    )


def _sanitize_enabled_skills(*, source: Path, snapshot: Path) -> None:
    source_path = source / "extensions" / "enabled_skills.json"
    snapshot_path = snapshot / "extensions" / "enabled_skills.json"
    if not snapshot_path.is_file():
        return
    config = EnabledSkillsConfig.model_validate_json(source_path.read_text(encoding="utf-8"))
    source_extension_root = (source / "extensions").resolve()
    skills = []
    for skill in config.skills:
        configured_path = Path(skill.path).expanduser()
        resolved = (
            configured_path.resolve()
            if configured_path.is_absolute()
            else (source_extension_root / configured_path).resolve()
        )
        try:
            relative = resolved.relative_to(source_extension_root)
        except ValueError as exc:
            raise PackageDistributionError(
                f"Skill {skill.skill_id!r} must be installed inside the package extensions directory"
            ) from exc
        distributed_path = snapshot / "extensions" / relative
        if not (distributed_path / "SKILL.md").is_file():
            raise PackageDistributionError(
                f"Skill {skill.skill_id!r} is configured but its package files are missing"
            )
        skills.append(skill.model_copy(update={"path": relative.as_posix()}))
    snapshot_path.write_text(
        config.model_copy(update={"skills": skills}).model_dump_json(indent=2),
        encoding="utf-8",
    )


def _sanitize_resource_defaults(snapshot: Path) -> None:
    manifest = read_manifest_payload(snapshot)
    contracts = manifest.get("contracts")
    if not isinstance(contracts, dict):
        return
    relative = contracts.get("resources")
    if not isinstance(relative, str):
        return
    path = snapshot / normalize_package_relative(relative)
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    config = payload.get("config") if isinstance(payload, dict) else None
    descriptors = config.get("resource_descriptors") if isinstance(config, dict) else None
    if not isinstance(descriptors, list):
        return
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            continue
        default_value = descriptor.get("default_value")
        for field_path in descriptor.get("secret_fields") or []:
            if isinstance(field_path, str):
                _remove_nested_value(default_value, field_path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _remove_nested_value(value: Any, field_path: str) -> None:
    parts = [part for part in field_path.split(".") if part]
    current = value
    for part in parts[:-1]:
        if not isinstance(current, dict):
            return
        current = current.get(part)
    if parts and isinstance(current, dict):
        current.pop(parts[-1], None)


def _without_host_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): sanitized
            for key, item in value.items()
            if (sanitized := _without_host_paths(item)) is not None
        }
    if isinstance(value, list):
        return [
            sanitized
            for item in value
            if (sanitized := _without_host_paths(item)) is not None
        ]
    if isinstance(value, str) and _host_absolute_path(value):
        return None
    return value


def _host_absolute_path(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    windows_path = PureWindowsPath(text)
    if windows_path.is_absolute():
        return True
    posix_path = PurePosixPath(text)
    if not posix_path.is_absolute():
        return False
    return not any(
        posix_path == root or root in posix_path.parents
        for root in (PurePosixPath("/workdir"), PurePosixPath("/package"))
    )


def _walk_json_strings(path: Path, text: str) -> Iterable[str]:
    if path.suffix.casefold() != ".json":
        return ()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ()
    return _iter_strings(payload)


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def _walk_json_items(path: Path, text: str) -> Iterable[tuple[str, Any]]:
    if path.suffix.casefold() != ".json":
        return ()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return ()
    return _iter_items(payload)


def _iter_items(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key), item
            yield from _iter_items(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_items(item)


def _looks_like_secret_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) < 8:
        return False
    return text.casefold() not in {
        "string",
        "password",
        "secret",
        "required",
        "optional",
        "configured",
    }


def _is_distribution_local_path(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    return (
        any(part in DISTRIBUTION_LOCAL_PARTS for part in path.parts)
        or path.name in DISTRIBUTION_LOCAL_NAMES
        or any(path.name.endswith(suffix) for suffix in DISTRIBUTION_LOCAL_SUFFIXES)
    )


def _add_manifest_file(files: set[str], value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        return
    relative = normalize_package_relative(value)
    if relative and not is_transient_package_path(relative):
        files.add(relative)


def _add_asset_dir_for_manifest_path(dirs: set[str], value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        return
    relative = normalize_package_relative(value)
    parts = relative.split("/")
    if parts and parts[0] in PACKAGE_ASSET_DIRS:
        dirs.add(parts[0] if len(parts) == 1 else "/".join(parts[:-1]))
