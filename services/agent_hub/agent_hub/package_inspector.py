from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any
import zipfile

from agent_hub.config import Settings


REQUIRED_CONTRACTS = frozenset(
    {
        "context",
        "dependencies",
        "knowledge",
        "memory",
        "model",
        "resources",
        "scheduler",
        "session",
        "state",
        "tools",
    }
)
TRANSIENT_ROOTS = frozenset({".agent_runtime", ".factory"})
TRANSIENT_NAMES = frozenset(
    {
        ".DS_Store",
        ".env",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
    }
)
TEXT_SUFFIXES = frozenset(
    {
        ".json",
        ".md",
        ".py",
        ".txt",
        ".yaml",
        ".yml",
        ".toml",
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".sh",
        ".ps1",
    }
)
PACKAGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
SECRET_PATTERNS = (
    ("aliyun_access_key", re.compile(r"\bLTAI[A-Za-z0-9]{12,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("generic_api_key", re.compile(r"(?i)(?:api[_-]?key|access[_-]?token)\s*[:=]\s*['\"][^'\"]{16,}")),
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_])/(?:Users|home|root)/[^\s\"']+"),
    re.compile(r"(?i)\b[A-Z]:\\Users\\[^\s\"']+"),
)
MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_SCANNED_TEXT_BYTES = 10 * 1024 * 1024
MAX_SINGLE_TEXT_SCAN_BYTES = 1 * 1024 * 1024


class PackageInspectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackageInspection:
    package_id: str
    name: str
    description: str
    version: str
    sha256: str
    archive_size: int
    file_count: int
    uncompressed_size: int
    package_root: str
    dependencies: dict[str, Any]
    tools: dict[str, Any]
    model: dict[str, Any]
    warnings: tuple[dict[str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "inspection_version": "agenthub.package_inspection.v1",
            "package_id": self.package_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "sha256": self.sha256,
            "archive_size": self.archive_size,
            "file_count": self.file_count,
            "uncompressed_size": self.uncompressed_size,
            "package_root": self.package_root,
            "dependencies": self.dependencies,
            "tools": self.tools,
            "model": self.model,
            "warnings": list(self.warnings),
        }


def inspect_package_archive(path: Path, settings: Settings) -> PackageInspection:
    archive_size = path.stat().st_size
    if archive_size <= 0:
        raise PackageInspectionError("archive_empty", "package archive is empty")
    if archive_size > settings.max_package_bytes:
        raise PackageInspectionError(
            "archive_too_large",
            f"package archive exceeds {settings.max_package_bytes} bytes",
        )
    digest = _file_sha256(path)
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise PackageInspectionError("archive_invalid", "package is not a valid ZIP archive") from exc
    with archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        _validate_archive_members(infos, settings=settings, archive_size=archive_size)
        manifest_name, package_root = _manifest_location(infos)
        manifest = _json_member(archive, manifest_name, label="agent_package.json")
        identity = _validate_manifest(archive, manifest, package_root=package_root)
        contracts = {
            contract_id: _json_member(
                archive,
                _package_member_name(package_root, relative_path),
                label=f"contracts.{contract_id}",
            )
            for contract_id, relative_path in manifest["contracts"].items()
        }
        warnings = _scan_archive_text(archive, infos)
        return PackageInspection(
            package_id=identity["id"],
            name=identity["name"],
            description=identity["description"],
            version=identity["version"],
            sha256=digest,
            archive_size=archive_size,
            file_count=len(infos),
            uncompressed_size=sum(item.file_size for item in infos),
            package_root=package_root,
            dependencies=_dependency_summary(contracts["dependencies"]),
            tools=_tool_summary(contracts["tools"], manifest),
            model=_model_summary(contracts["model"]),
            warnings=tuple(warnings),
        )


def _validate_archive_members(
    infos: list[zipfile.ZipInfo],
    *,
    settings: Settings,
    archive_size: int,
) -> None:
    if not infos:
        raise PackageInspectionError("archive_empty", "package archive contains no files")
    if len(infos) > settings.max_archive_files:
        raise PackageInspectionError(
            "archive_file_limit",
            f"package archive contains more than {settings.max_archive_files} files",
        )
    total_size = 0
    seen: set[str] = set()
    for info in infos:
        member = _safe_member_path(info.filename)
        if member in seen:
            raise PackageInspectionError("archive_duplicate_path", f"duplicate path: {member}")
        seen.add(member)
        total_size += info.file_size
        if total_size > settings.max_uncompressed_bytes:
            raise PackageInspectionError(
                "archive_uncompressed_limit",
                f"uncompressed package exceeds {settings.max_uncompressed_bytes} bytes",
            )
        if _is_symlink(info):
            raise PackageInspectionError("archive_symlink", f"symbolic links are not allowed: {member}")
        path_parts = PurePosixPath(member).parts
        if any(part in TRANSIENT_ROOTS for part in path_parts):
            raise PackageInspectionError(
                "archive_transient_runtime",
                f"runtime directory is not publishable: {member}",
            )
        if any(part in TRANSIENT_NAMES for part in path_parts):
            raise PackageInspectionError(
                "archive_transient_file",
                f"transient or secret file is not publishable: {member}",
            )
        if member.endswith((".pyc", ".pyo")):
            raise PackageInspectionError(
                "archive_compiled_python",
                f"compiled Python files are not publishable: {member}",
            )
    if archive_size > 0 and total_size / archive_size > settings.max_compression_ratio:
        raise PackageInspectionError(
            "archive_compression_ratio",
            f"archive compression ratio exceeds {settings.max_compression_ratio}",
        )


def _manifest_location(infos: list[zipfile.ZipInfo]) -> tuple[str, str]:
    candidates = [
        _safe_member_path(info.filename)
        for info in infos
        if PurePosixPath(_safe_member_path(info.filename)).name == "agent_package.json"
    ]
    valid = [
        name
        for name in candidates
        if len(PurePosixPath(name).parts) in {1, 2}
    ]
    if len(valid) != 1:
        raise PackageInspectionError(
            "manifest_location",
            "archive must contain exactly one root agent_package.json",
        )
    parts = PurePosixPath(valid[0]).parts
    return valid[0], parts[0] if len(parts) == 2 else ""


def _validate_manifest(
    archive: zipfile.ZipFile,
    manifest: dict[str, Any],
    *,
    package_root: str,
) -> dict[str, str]:
    if manifest.get("version") != "agent_package.v0":
        raise PackageInspectionError(
            "manifest_version",
            "agent_package.json version must be agent_package.v0",
        )
    identity = manifest.get("agent")
    if not isinstance(identity, dict):
        raise PackageInspectionError("manifest_agent", "agent_package.json agent must be an object")
    package_id = str(identity.get("id") or "").strip()
    if not PACKAGE_ID_PATTERN.fullmatch(package_id):
        raise PackageInspectionError("manifest_package_id", "agent id is invalid")
    version = str(identity.get("version") or "").strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise PackageInspectionError("manifest_semver", "agent version must be valid SemVer")
    name = str(identity.get("name") or package_id).strip()
    description = str(identity.get("description") or "").strip()
    if not name:
        raise PackageInspectionError("manifest_name", "agent name must not be empty")
    contracts = manifest.get("contracts")
    if not isinstance(contracts, dict):
        raise PackageInspectionError(
            "manifest_contracts",
            "agent_package.json contracts must be an object",
        )
    missing = sorted(REQUIRED_CONTRACTS - set(contracts))
    if missing:
        raise PackageInspectionError(
            "manifest_contracts_missing",
            "missing required contracts: " + ", ".join(missing),
        )
    references = [
        ("assembly_spec_path", manifest.get("assembly_spec_path")),
        *[(f"contracts.{key}", value) for key, value in contracts.items()],
        *[
            (f"tools[{index}]", value)
            for index, value in enumerate(manifest.get("tools") or [])
        ],
    ]
    archive_names = set(archive.namelist())
    for label, raw_path in references:
        relative_path = _safe_package_relative(raw_path, label=label)
        member_name = _package_member_name(package_root, relative_path)
        if member_name not in archive_names:
            raise PackageInspectionError(
                "manifest_reference_missing",
                f"{label} references missing file: {relative_path}",
            )
    return {
        "id": package_id,
        "name": name[:200],
        "description": description[:2_000],
        "version": version,
    }


def _safe_member_path(raw_path: str) -> str:
    if not raw_path or "\x00" in raw_path or "\\" in raw_path:
        raise PackageInspectionError("archive_path", f"invalid archive path: {raw_path!r}")
    path = PurePosixPath(raw_path)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PackageInspectionError("archive_path", f"unsafe archive path: {raw_path}")
    return path.as_posix()


def _safe_package_relative(raw_path: Any, *, label: str) -> str:
    value = str(raw_path or "").strip()
    if not value or "\\" in value:
        raise PackageInspectionError("manifest_reference", f"{label} must be package-relative")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PackageInspectionError("manifest_reference", f"{label} escapes package root")
    return path.as_posix()


def _package_member_name(package_root: str, relative_path: str) -> str:
    return (
        (PurePosixPath(package_root) / relative_path).as_posix()
        if package_root
        else relative_path
    )


def _json_member(archive: zipfile.ZipFile, name: str, *, label: str) -> dict[str, Any]:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise PackageInspectionError(
            "json_member_missing", f"{label} is missing: {name}"
        ) from exc
    if info.file_size > MAX_JSON_BYTES:
        raise PackageInspectionError("json_member_too_large", f"{label} is too large")
    try:
        value = json.loads(archive.read(info).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageInspectionError("json_member_invalid", f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PackageInspectionError("json_member_type", f"{label} must be a JSON object")
    return value


def _dependency_summary(contract: dict[str, Any]) -> dict[str, Any]:
    config = contract.get("config") if isinstance(contract.get("config"), dict) else contract
    python_items = _string_list(
        config.get("python")
        or config.get("python_requirements")
        or config.get("requirements")
    )
    npm_items = _string_list(config.get("npm") or config.get("npm_dependencies"))
    system_items = _string_list(
        config.get("system") or config.get("system_dependencies") or config.get("commands")
    )
    return {
        "python": python_items,
        "npm": npm_items,
        "system": system_items,
        "python_count": len(python_items),
        "npm_count": len(npm_items),
        "system_count": len(system_items),
    }


def _tool_summary(contract: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    config = contract.get("config") if isinstance(contract.get("config"), dict) else contract
    builtins = _string_list(config.get("builtin_tools") or config.get("builtins"))
    package_tools = [
        str(item)
        for item in manifest.get("tools") or []
        if isinstance(item, str) and item.strip()
    ]
    mcp_servers = _string_list(config.get("mcp_servers") or config.get("mcp"))
    permissions = config.get("approval_policy") or config.get("permissions") or {}
    return {
        "builtin_tools": builtins,
        "package_tools": package_tools,
        "mcp_servers": mcp_servers,
        "permissions": permissions if isinstance(permissions, (dict, list)) else {},
    }


def _model_summary(contract: dict[str, Any]) -> dict[str, Any]:
    config = contract.get("config") if isinstance(contract.get("config"), dict) else contract
    requirements = config.get("requirements") or config.get("capabilities") or {}
    return {
        "requirements": requirements if isinstance(requirements, (dict, list)) else {},
        "profile_references": _string_list(
            config.get("profile_ids") or config.get("profiles")
        ),
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, dict):
        return sorted(str(key) for key in value if str(key).strip())
    if not isinstance(value, list):
        return []
    return sorted(
        {
            str(item).strip()
            for item in value
            if isinstance(item, (str, int, float)) and str(item).strip()
        }
    )


def _scan_archive_text(
    archive: zipfile.ZipFile,
    infos: list[zipfile.ZipInfo],
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    scanned = 0
    for info in infos:
        if PurePosixPath(info.filename).suffix.lower() not in TEXT_SUFFIXES:
            continue
        if info.file_size > MAX_SINGLE_TEXT_SCAN_BYTES:
            continue
        if scanned + info.file_size > MAX_SCANNED_TEXT_BYTES:
            break
        scanned += info.file_size
        try:
            content = archive.read(info).decode("utf-8")
        except UnicodeDecodeError:
            continue
        for code, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                raise PackageInspectionError(
                    "secret_detected",
                    f"possible {code} detected in {info.filename}",
                )
        for pattern in ABSOLUTE_PATH_PATTERNS:
            if pattern.search(content):
                warnings.append(
                    {
                        "code": "host_absolute_path",
                        "path": info.filename,
                        "message": "possible host absolute path detected",
                    }
                )
                break
    return warnings


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
