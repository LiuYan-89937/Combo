from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any
import zipfile

from agent_hub.config import Settings
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


TRANSIENT_ROOTS = frozenset({".agent_runtime", ".factory", "checkpoints", "logs", "sessions"})
TRANSIENT_NAMES = frozenset(
    {
        ".DS_Store",
        ".env",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "agent.sqlite",
        "runtime.sqlite",
    }
)
PACKAGE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
MAX_JSON_BYTES = 5 * 1024 * 1024
PACKAGE_SCHEMA_RESOURCE = "agent_package_schemas.json"


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
            "inspection_version": "agenthub.package_inspection.v2",
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


@dataclass(frozen=True, slots=True)
class PackageSchemaRegistry:
    required_contracts: frozenset[str]
    supported_contracts: frozenset[str]
    manifest: Draft202012Validator
    assembly_spec: Draft202012Validator
    contracts: dict[str, Draft202012Validator]

    @classmethod
    def load(cls) -> "PackageSchemaRegistry":
        resource = files("agent_hub").joinpath(PACKAGE_SCHEMA_RESOURCE)
        payload = json.loads(resource.read_text(encoding="utf-8"))
        if payload.get("version") != "agenthub.package_schemas.v1":
            raise RuntimeError("unsupported AgentHub package schema bundle")
        contract_schemas = payload.get("contracts")
        if not isinstance(contract_schemas, dict):
            raise RuntimeError("AgentHub package schema bundle has no contract schemas")
        manifest_schema = _schema_object(payload.get("manifest"), label="manifest")
        assembly_schema = _schema_object(payload.get("assembly_spec"), label="assembly_spec")
        schemas = {
            str(contract_id): _schema_object(schema, label=f"contracts.{contract_id}")
            for contract_id, schema in contract_schemas.items()
        }
        for schema in (manifest_schema, assembly_schema, *schemas.values()):
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                raise RuntimeError("AgentHub package schema bundle is invalid") from exc
        required = _schema_string_set(payload.get("required_contracts"), label="required_contracts")
        supported = _schema_string_set(payload.get("supported_contracts"), label="supported_contracts")
        if required - supported or supported != frozenset(schemas):
            raise RuntimeError("AgentHub package schema contract catalog is inconsistent")
        return cls(
            required_contracts=required,
            supported_contracts=supported,
            manifest=Draft202012Validator(manifest_schema),
            assembly_spec=Draft202012Validator(assembly_schema),
            contracts={
                contract_id: Draft202012Validator(schema)
                for contract_id, schema in schemas.items()
            },
        )

    def validate_manifest(self, payload: dict[str, Any]) -> None:
        _validate_schema(self.manifest, payload, label="agent_package.json")

    def validate_assembly_spec(self, payload: dict[str, Any]) -> None:
        _validate_schema(self.assembly_spec, payload, label="assembly_spec")

    def validate_contract(self, contract_id: str, payload: dict[str, Any]) -> None:
        try:
            validator = self.contracts[contract_id]
        except KeyError as exc:
            raise PackageInspectionError(
                "manifest_contracts_unsupported",
                f"unsupported contract: {contract_id}",
            ) from exc
        _validate_schema(validator, payload, label=f"contracts.{contract_id}")


def _schema_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"AgentHub package schema {label} must be an object")
    return value


def _schema_string_set(value: Any, *, label: str) -> frozenset[str]:
    if not isinstance(value, list):
        raise RuntimeError(f"AgentHub package schema {label} must be an array")
    result = frozenset(
        str(item).strip()
        for item in value
        if isinstance(item, str) and item.strip()
    )
    if len(result) != len(value):
        raise RuntimeError(f"AgentHub package schema {label} contains invalid values")
    return result


def _validate_schema(
    validator: Draft202012Validator,
    payload: dict[str, Any],
    *,
    label: str,
) -> None:
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    location = ".".join(str(part) for part in error.absolute_path)
    subject = f"{label}.{location}" if location else label
    raise PackageInspectionError(
        "package_contract_invalid",
        f"{subject}: {error.message}",
    )


PACKAGE_SCHEMAS = PackageSchemaRegistry.load()


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
        assembly_spec = _json_member(
            archive,
            _package_member_name(package_root, manifest["assembly_spec_path"]),
            label="assembly_spec",
        )
        PACKAGE_SCHEMAS.validate_assembly_spec(assembly_spec)
        contracts = {
            contract_id: _json_member(
                archive,
                _package_member_name(package_root, relative_path),
                label=f"contracts.{contract_id}",
            )
            for contract_id, relative_path in manifest["contracts"].items()
        }
        for contract_id, contract in contracts.items():
            PACKAGE_SCHEMAS.validate_contract(contract_id, contract)
        warnings = _validate_distribution_extensions(
            archive,
            infos,
            package_root=package_root,
        )
        _validate_resource_defaults(contracts["resources"])
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
        if (
            PurePosixPath(member).name.startswith(".env.")
            or member.endswith((".log", ".pyc", ".pyo"))
        ):
            raise PackageInspectionError(
                "archive_transient_suffix",
                f"runtime or compiled file is not publishable: {member}",
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
    PACKAGE_SCHEMAS.validate_manifest(manifest)
    identity = manifest["agent"]
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
    contracts = manifest["contracts"]
    missing = sorted(PACKAGE_SCHEMAS.required_contracts - set(contracts))
    if missing:
        raise PackageInspectionError(
            "manifest_contracts_missing",
            "missing required contracts: " + ", ".join(missing),
        )
    unsupported = sorted(set(contracts) - PACKAGE_SCHEMAS.supported_contracts)
    if unsupported:
        raise PackageInspectionError(
            "manifest_contracts_unsupported",
            "unsupported contracts are not accepted: " + ", ".join(unsupported),
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
    config = contract["config"]
    python_items = _string_list(config.get("python_requirements"))
    npm_items = _string_list(config.get("npm_requirements"))
    system_items = _string_list(config.get("system_binaries"))
    return {
        "python": python_items,
        "npm": npm_items,
        "system": system_items,
        "python_count": len(python_items),
        "npm_count": len(npm_items),
        "system_count": len(system_items),
    }


def _tool_summary(contract: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    config = contract["config"]
    builtins = _string_list(config.get("builtin_tool_ids"))
    package_tools = [
        str(item)
        for item in manifest.get("tools") or []
        if isinstance(item, str) and item.strip()
    ]
    permissions = config.get("approval_policy") or {}
    return {
        "builtin_tools": builtins,
        "package_tools": package_tools,
        "permissions": permissions,
    }


def _model_summary(contract: dict[str, Any]) -> dict[str, Any]:
    config = contract["config"]
    bindings = config.get("bindings") or {}
    tool_bindings = config.get("tool_bindings") or {}
    return {
        "bindings": _binding_requirements(bindings),
        "tool_bindings": _tool_binding_requirements(tool_bindings),
    }


def _binding_requirements(value: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for role, raw_binding in value.items():
        result[str(role)] = {
            "reason": str(raw_binding.get("reason") or ""),
            "required_capabilities": (
                dict(raw_binding["required_capabilities"])
                if isinstance(raw_binding.get("required_capabilities"), dict)
                else {}
            ),
        }
    return result


def _tool_binding_requirements(value: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for tool_id, raw_binding in value.items():
        result[str(tool_id)] = {
            "capability": str(raw_binding.get("capability") or ""),
            "description": str(raw_binding.get("description") or ""),
            "reason": str(raw_binding.get("reason") or ""),
            "required_capabilities": (
                dict(raw_binding["required_capabilities"])
                if isinstance(raw_binding.get("required_capabilities"), dict)
                else {}
            ),
        }
    return result


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    return sorted(set(value))


def _validate_distribution_extensions(
    archive: zipfile.ZipFile,
    infos: list[zipfile.ZipInfo],
    *,
    package_root: str,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    names = {info.filename for info in infos}
    mcp_name = _package_member_name(package_root, "extensions/mcp_servers.json")
    if mcp_name in names:
        payload = _json_member(archive, mcp_name, label="extensions/mcp_servers.json")
        servers = payload.get("servers")
        if not isinstance(servers, list):
            raise PackageInspectionError(
                "mcp_config",
                "extensions/mcp_servers.json servers must be an array",
            )
        for server in servers:
            if not isinstance(server, dict):
                raise PackageInspectionError("mcp_config", "MCP server entries must be objects")
            server_id = str(server.get("server_id") or "unknown")
            review_fields = [
                field
                for field in ("env", "headers", "cwd")
                if server.get(field) not in ({}, "", None)
            ]
            if review_fields:
                warnings.append(
                    {
                        "code": "mcp_private_configuration_reviewed",
                        "path": mcp_name,
                        "message": (
                            f"MCP server {server_id} includes user-reviewed fields: "
                            + ", ".join(review_fields)
                        ),
                    }
                )

    skills_name = _package_member_name(package_root, "extensions/enabled_skills.json")
    if skills_name in names:
        payload = _json_member(archive, skills_name, label="extensions/enabled_skills.json")
        skills = payload.get("skills")
        if not isinstance(skills, list):
            raise PackageInspectionError(
                "skill_config",
                "extensions/enabled_skills.json skills must be an array",
            )
        for skill in skills:
            if not isinstance(skill, dict):
                raise PackageInspectionError("skill_config", "Skill entries must be objects")
            path = _safe_package_relative(skill.get("path"), label="skill.path")
            skill_file = _package_member_name(
                package_root,
                (PurePosixPath("extensions") / path / "SKILL.md").as_posix(),
            )
            if skill_file not in names:
                raise PackageInspectionError(
                    "skill_files_missing",
                    f"distributed Skill is missing SKILL.md: {path}",
                )
    return warnings


def _validate_resource_defaults(contract: dict[str, Any]) -> None:
    config = contract.get("config")
    descriptors = config.get("resource_descriptors") if isinstance(config, dict) else None
    if not isinstance(descriptors, list):
        return
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            continue
        default_value = descriptor.get("default_value")
        for field_path in descriptor.get("secret_fields") or []:
            if isinstance(field_path, str) and _nested_value_exists(default_value, field_path):
                raise PackageInspectionError(
                    "resource_secret_default",
                    "resource descriptor default_value contains a declared secret field",
                )


def _nested_value_exists(value: Any, field_path: str) -> bool:
    current = value
    separator = "/" if field_path.startswith("/") else "."
    parts = [part for part in field_path.split(separator) if part]
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return bool(parts)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
