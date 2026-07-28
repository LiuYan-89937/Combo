from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
from typing import Any
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


def distribution_extension_preview(source: Path, package_id: str) -> dict[str, Any]:
    _require_package_id(source, package_id)
    return {
        "package_id": package_id,
        "mcp_servers": _read_extension_config(
            source / "extensions" / "mcp_servers.json",
            default=MCPServersConfig().model_dump(mode="json"),
        ),
        "skills": _distribution_skills(source),
    }


def export_distribution_archive(
    source: Path,
    package_id: str,
    archive_path: Path,
    *,
    extension_overrides: dict[str, Any] | None = None,
) -> None:
    _require_package_id(source, package_id)
    overrides = _validate_extension_overrides(extension_overrides)
    with tempfile.TemporaryDirectory(prefix="agent-package-distribution-") as temp_dir:
        snapshot_root = Path(temp_dir) / source.name
        copy_publishable_package(source, snapshot_root)
        skill_paths = _normalize_distribution_skills(source=source, snapshot=snapshot_root)
        _apply_extension_overrides(snapshot_root, overrides, skill_paths=skill_paths)
        _sanitize_resource_defaults(snapshot_root)
        validate_distribution_snapshot(snapshot_root)
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(item for item in snapshot_root.rglob("*") if item.is_file()):
                relative = Path(source.name) / path.relative_to(snapshot_root)
                archive.write(path, relative.as_posix())


def _require_package_id(source: Path, package_id: str) -> None:
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
    separator = "/" if field_path.startswith("/") else "."
    parts = [part for part in field_path.split(separator) if part]
    current = value
    for part in parts[:-1]:
        if not isinstance(current, dict):
            return
        current = current.get(part)
    if parts and isinstance(current, dict):
        current.pop(parts[-1], None)


def _read_extension_config(path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PackageDistributionError(f"extension configuration is not readable: {path.name}") from exc
    if not isinstance(payload, dict):
        raise PackageDistributionError(f"extension configuration must be an object: {path.name}")
    return payload


def _validate_extension_overrides(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PackageDistributionError("extension overrides must be an object")
    unknown = sorted(set(value) - {"mcp_servers", "skills"})
    if unknown:
        raise PackageDistributionError("unsupported extension overrides: " + ", ".join(unknown))
    overrides: dict[str, Any] = {}
    if "mcp_servers" in value:
        overrides["mcp_servers"] = MCPServersConfig.model_validate(
            value["mcp_servers"]
        ).model_dump(mode="json")
    if "skills" in value:
        raw_skills = value["skills"]
        if not isinstance(raw_skills, list):
            raise PackageDistributionError("Skill content overrides must be an array")
        skill_files: dict[str, list[dict[str, Any]]] = {}
        for item in raw_skills:
            if not isinstance(item, dict):
                raise PackageDistributionError("Skill content overrides must contain objects")
            skill_id = str(item.get("skill_id") or "").strip()
            files = item.get("files")
            if not skill_id or not isinstance(files, list):
                raise PackageDistributionError("Skill override requires skill_id and files")
            if skill_id in skill_files:
                raise PackageDistributionError(f"duplicate Skill content override: {skill_id}")
            normalized_files: list[dict[str, Any]] = []
            seen_paths: set[str] = set()
            for file_item in files:
                if not isinstance(file_item, dict):
                    raise PackageDistributionError("Skill file overrides must contain objects")
                relative_path = _safe_skill_file_path(file_item.get("path"))
                if relative_path in seen_paths:
                    raise PackageDistributionError(
                        f"duplicate Skill file override: {skill_id}/{relative_path}"
                    )
                included = file_item.get("included") is not False
                content = file_item.get("content")
                if content is not None and not isinstance(content, str):
                    raise PackageDistributionError(
                        f"Skill text content must be a string: {skill_id}/{relative_path}"
                    )
                normalized_files.append(
                    {
                        "path": relative_path,
                        "included": included,
                        "content": content,
                    }
                )
                seen_paths.add(relative_path)
            skill_files[skill_id] = normalized_files
        overrides["skills"] = skill_files
    return overrides


def _apply_extension_overrides(
    root: Path,
    overrides: dict[str, Any],
    *,
    skill_paths: dict[str, Path],
) -> None:
    mcp_payload = overrides.get("mcp_servers")
    if mcp_payload is not None:
        path = root / "extensions" / "mcp_servers.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(mcp_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    skill_overrides = overrides.get("skills")
    if skill_overrides is None:
        return
    unknown = sorted(set(skill_overrides) - set(skill_paths))
    if unknown:
        raise PackageDistributionError(
            "Skill content override references unconfigured Skills: " + ", ".join(unknown)
        )
    for skill_id, file_overrides in skill_overrides.items():
        skill_root = root / "extensions" / skill_paths[skill_id]
        available = {
            path.relative_to(skill_root).as_posix(): path
            for path in skill_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        requested = {item["path"]: item for item in file_overrides}
        unknown_files = sorted(set(requested) - set(available))
        if unknown_files:
            raise PackageDistributionError(
                f"Skill {skill_id!r} override references unknown files: "
                + ", ".join(unknown_files)
            )
        entry = requested.get("SKILL.md")
        if entry is None or entry["included"] is not True:
            raise PackageDistributionError(f"Skill {skill_id!r} must include SKILL.md")
        for relative_path, item in requested.items():
            path = available[relative_path]
            if item["included"] is not True:
                path.unlink()
                continue
            content = item.get("content")
            if content is not None:
                try:
                    path.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    raise PackageDistributionError(
                        f"binary Skill resource cannot be edited as text: {skill_id}/{relative_path}"
                    ) from exc
                path.write_text(content, encoding="utf-8")


def _distribution_skills(source: Path) -> list[dict[str, Any]]:
    config = _load_enabled_skills(source)
    skill_paths = _portable_skill_paths(source, config)
    return [
        {
            "skill_id": skill.skill_id,
            "source": skill.source,
            "enabled": skill.enabled,
            "required": skill.required,
            "path": skill_paths[skill.skill_id].as_posix(),
            "files": _skill_file_inventory(
                source / "extensions" / skill_paths[skill.skill_id]
            ),
        }
        for skill in config.skills
    ]


def _normalize_distribution_skills(*, source: Path, snapshot: Path) -> dict[str, Path]:
    config = _load_enabled_skills(source)
    skill_paths = _portable_skill_paths(source, config)
    if not config.skills:
        return skill_paths
    skills = [
        skill.model_copy(update={"path": skill_paths[skill.skill_id].as_posix()})
        for skill in config.skills
    ]
    path = snapshot / "extensions" / "enabled_skills.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        config.model_copy(update={"skills": skills}).model_dump_json(indent=2),
        encoding="utf-8",
    )
    return skill_paths


def _load_enabled_skills(source: Path) -> EnabledSkillsConfig:
    payload = _read_extension_config(
        source / "extensions" / "enabled_skills.json",
        default=EnabledSkillsConfig().model_dump(mode="json"),
    )
    return EnabledSkillsConfig.model_validate(payload)


def _portable_skill_paths(
    source: Path,
    config: EnabledSkillsConfig,
) -> dict[str, Path]:
    extension_root = (source / "extensions").resolve()
    result: dict[str, Path] = {}
    for skill in config.skills:
        configured = Path(skill.path).expanduser()
        resolved = (
            configured.resolve()
            if configured.is_absolute()
            else (extension_root / configured).resolve()
        )
        try:
            relative = resolved.relative_to(extension_root)
        except ValueError as exc:
            raise PackageDistributionError(
                f"Skill {skill.skill_id!r} must be installed inside the package extensions directory"
            ) from exc
        if not (resolved / "SKILL.md").is_file():
            raise PackageDistributionError(
                f"Skill {skill.skill_id!r} is configured but SKILL.md is missing"
            )
        result[skill.skill_id] = relative
    return result


def _skill_file_inventory(root: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            files.append(
                {
                    "path": relative,
                    "size_bytes": size,
                    "kind": "binary",
                    "included": True,
                    "content": None,
                }
            )
        else:
            files.append(
                {
                    "path": relative,
                    "size_bytes": size,
                    "kind": "text",
                    "included": True,
                    "content": content,
                }
            )
    return files


def _safe_skill_file_path(value: Any) -> str:
    text = str(value or "").strip()
    path = PurePosixPath(text)
    if (
        not text
        or "\\" in text
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise PackageDistributionError(f"invalid Skill file path: {text!r}")
    return path.as_posix()


def _is_distribution_local_path(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    return (
        any(part in DISTRIBUTION_LOCAL_PARTS for part in path.parts)
        or path.name in DISTRIBUTION_LOCAL_NAMES
        or path.name.startswith(".env.")
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
