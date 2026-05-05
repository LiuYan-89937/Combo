from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from agent_factory.factory_runtime.redaction import redact_secrets


DB_SUFFIXES = {".db", ".duckdb", ".sqlite", ".sqlite3"}


@dataclass
class SandboxResource:
    source_id: str
    resource_type: str
    original_path: Path
    sandbox_path: Path
    before_hash: str | None = None
    after_hash: str | None = None


@dataclass
class ToolTestSandbox:
    root_path: Path
    package_path: Path
    context_path: Path
    context: dict[str, Any]
    resources: list[SandboxResource] = field(default_factory=list)

    @property
    def resource_count(self) -> int:
        return len(self.resources)

    @property
    def resource_map_redacted(self) -> dict[str, Any]:
        return redact_secrets(
            {
                resource.source_id: {
                    "type": resource.resource_type,
                    "path": _safe_display_path(resource.sandbox_path),
                }
                for resource in self.resources
            }
        )

    def unsafe_real_resource_issues(self) -> list[dict[str, str]]:
        issues: list[dict[str, str]] = []
        real_paths = [str(resource.original_path) for resource in self.resources]
        for script in sorted((self.package_path / "generated" / "draft_tools").glob("*.py")):
            try:
                source = script.read_text(encoding="utf-8")
            except OSError:
                continue
            for real_path in real_paths:
                if not real_path or real_path not in source:
                    continue
                if "_resolve_db_path" in source or "sqlite_databases" in source or "resources" in source:
                    continue
                issues.append(
                    {
                        "code": "tool_used_real_resource_path",
                        "message": "Generated tool references a real resource path without sandbox context resolution.",
                        "path": str(script.relative_to(self.package_path)),
                    }
                )
        return issues

    def diff_summary(self) -> dict[str, Any]:
        changed: list[str] = []
        unchanged: list[str] = []
        missing: list[str] = []
        for resource in self.resources:
            resource.after_hash = _hash_path(resource.sandbox_path)
            if resource.after_hash is None:
                missing.append(resource.source_id)
            elif resource.before_hash != resource.after_hash:
                changed.append(resource.source_id)
            else:
                unchanged.append(resource.source_id)
        return {
            "changed_resources": changed,
            "unchanged_resources": unchanged,
            "missing_resources": missing,
            "changed_count": len(changed),
            "resource_count": len(self.resources),
        }

    def cleanup(self) -> None:
        shutil.rmtree(self.root_path, ignore_errors=True)


class SandboxResourceResolver:
    def __init__(self) -> None:
        self._yaml = YAML(typ="safe")

    def prepare(self, package_path: Path) -> ToolTestSandbox:
        root = Path(tempfile.mkdtemp(prefix=f"agentfactory-tool-sandbox-{uuid.uuid4().hex[:8]}-"))
        sandbox_package = root / "package"
        shutil.copytree(package_path, sandbox_package)
        for directory in [
            root / "resources" / "files",
            root / "resources" / "sqlite",
            root / "resources" / "directories",
            root / "resources" / "mcp",
            root / "runtime" / "tmp",
            root / "runtime" / "memory",
            root / "runtime" / "traces",
        ]:
            directory.mkdir(parents=True, exist_ok=True)

        resources = self._copy_resources(package_path, root)
        context = self._build_context(root, resources)
        context_path = root / "tool_test_context.json"
        context_path.write_text(json.dumps(redact_secrets(context), ensure_ascii=False), encoding="utf-8")
        return ToolTestSandbox(
            root_path=root,
            package_path=sandbox_package,
            context_path=context_path,
            context=context,
            resources=resources,
        )

    def _copy_resources(self, package_path: Path, root: Path) -> list[SandboxResource]:
        resources: list[SandboxResource] = []
        for source in self._resource_sources(package_path):
            source_id = _safe_id(str(source.get("id") or "resource"))
            ref = source.get("ref")
            if not isinstance(ref, str) or not ref.strip():
                continue
            original = _resolve_ref(package_path, ref)
            if original is None or not original.exists():
                continue
            resource_type = _resource_type(original, str(source.get("type") or ""))
            target = _target_path(root, source_id, original, resource_type)
            target.parent.mkdir(parents=True, exist_ok=True)
            if original.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(original, target)
            else:
                shutil.copy2(original, target)
            resources.append(
                SandboxResource(
                    source_id=source_id,
                    resource_type=resource_type,
                    original_path=original,
                    sandbox_path=target,
                    before_hash=_hash_path(target),
                )
            )
        return resources

    def _resource_sources(self, package_path: Path) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for file_name in ("knowledge.yaml", "context.yaml"):
            data = self._load_mapping(package_path / file_name)
            raw_sources = data.get("sources") if isinstance(data, dict) else None
            if not isinstance(raw_sources, list):
                continue
            for item in raw_sources:
                if isinstance(item, dict):
                    sources.append(item)
        return _dedupe_sources(sources)

    def _load_mapping(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        data = self._yaml.load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def _build_context(self, root: Path, resources: list[SandboxResource]) -> dict[str, Any]:
        external_config_path = root / "package" / "external_config.yaml"
        external_config_data = self._load_mapping(external_config_path)
        external_values = external_config_data.get("values") if isinstance(external_config_data, dict) else {}
        external_required = (
            external_config_data.get("required_keys") if isinstance(external_config_data, dict) else []
        )
        external_secret = external_config_data.get("secret_keys") if isinstance(external_config_data, dict) else []
        external_sources = (
            external_config_data.get("source_urls") if isinstance(external_config_data, dict) else []
        )
        values = _string_map(external_values)
        required_keys = _string_list(external_required)
        missing_required = [key for key in required_keys if not values.get(key)]
        context: dict[str, Any] = {
            "sandbox": {"enabled": True, "mode": "process_directory"},
            "resources": {},
            "sqlite_databases": {},
            "filesystem_root": str(root / "resources" / "files"),
            "runtime": {
                "tmp_dir": str(root / "runtime" / "tmp"),
                "memory_dir": str(root / "runtime" / "memory"),
                "trace_dir": str(root / "runtime" / "traces"),
            },
            "external_config": {
                "path": str(external_config_path),
                "exists": external_config_path.exists(),
                "status": (
                    "needs_user_configuration"
                    if external_config_path.exists() and missing_required
                    else "ready"
                    if external_config_path.exists()
                    else "missing"
                ),
                "data": external_config_data,
                "values": values,
                "resolved_values": values,
                "required_keys": required_keys,
                "secret_keys": _string_list(external_secret),
                "source_urls": _string_list(external_sources),
                "missing_required_keys": missing_required,
            },
        }
        for resource in resources:
            context["resources"][resource.source_id] = {
                "type": resource.resource_type,
                "path": str(resource.sandbox_path),
            }
            if resource.resource_type == "sqlite":
                context["sqlite_databases"][resource.source_id] = str(resource.sandbox_path)
        return context


def _resolve_ref(package_path: Path, ref: str) -> Path | None:
    path = Path(ref).expanduser()
    if path.is_absolute():
        return path
    return package_path / path


def _resource_type(path: Path, declared_type: str) -> str:
    if declared_type == "directory" or path.is_dir():
        return "directory"
    if path.suffix.lower() in DB_SUFFIXES:
        return "sqlite"
    if declared_type == "mcp":
        return "mcp"
    return "file"


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _target_path(root: Path, source_id: str, original: Path, resource_type: str) -> Path:
    if resource_type == "sqlite":
        suffix = original.suffix if original.suffix else ".sqlite3"
        return root / "resources" / "sqlite" / f"{source_id}{suffix}"
    if resource_type == "directory":
        return root / "resources" / "directories" / source_id
    if resource_type == "mcp":
        return root / "resources" / "mcp" / source_id
    return root / "resources" / "files" / source_id / original.name


def _hash_path(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    if path.is_dir():
        for item in sorted(child for child in path.rglob("*") if child.is_file()):
            digest.update(str(item.relative_to(path)).encode("utf-8"))
            digest.update(item.read_bytes())
    else:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _safe_id(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value)
    return cleaned.strip("_") or "resource"


def _safe_display_path(path: Path) -> str:
    return str(path)


def _dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for source in sources:
        key = (str(source.get("id") or ""), str(source.get("ref") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped
