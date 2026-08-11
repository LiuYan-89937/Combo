from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass, field
from types import MappingProxyType
from collections.abc import Mapping
from typing import Any

from agent_factory.tooling.spec import ToolRiskResult
from agent_factory.tooling.workspace_paths import workspace_path_candidate


SENSITIVE_FILE_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}
SENSITIVE_DIR_NAMES = {".ssh", ".gnupg", "secrets", "secret", "credentials"}


@dataclass(frozen=True, slots=True)
class FilesystemRuntimeResource:
    root: Path
    staged_write_store: Any
    transaction_store: Any
    allow_external: bool = False
    allowed_roots: tuple[Path, ...] = ()
    mounts: Mapping[str, Path] = field(default_factory=dict)
    protected_write_paths: tuple[Path, ...] = ()
    read_only_paths: tuple[Path, ...] = ()
    managed_paths: Mapping[Path, Mapping[str, Any]] = field(default_factory=dict)
    managed_write_paths: Mapping[Path, Mapping[str, Any]] = field(default_factory=dict)
    allowed_write_paths: tuple[Path, ...] = ()
    write_scope_enforced: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.expanduser().resolve())
        for field_name in (
            "allowed_roots",
            "protected_write_paths",
            "read_only_paths",
            "allowed_write_paths",
        ):
            object.__setattr__(
                self,
                field_name,
                tuple(Path(path).expanduser().resolve() for path in getattr(self, field_name)),
            )
        object.__setattr__(self, "mounts", MappingProxyType(dict(self.mounts)))
        object.__setattr__(self, "managed_paths", MappingProxyType(dict(self.managed_paths)))
        object.__setattr__(self, "managed_write_paths", MappingProxyType(dict(self.managed_write_paths)))

    def tool_resource_context(self) -> dict[str, Any]:
        return {
            "schema": "filesystem_runtime_context.v1",
            "root": str(self.root),
            "allow_external": self.allow_external,
            "allowed_roots": [str(path) for path in self.allowed_roots],
            "protected_write_paths": [str(path) for path in self.protected_write_paths],
            "read_only_paths": [str(path) for path in self.read_only_paths],
            "managed_paths": {str(path): dict(spec) for path, spec in self.managed_paths.items()},
            "managed_write_paths": {
                str(path): dict(spec) for path, spec in self.managed_write_paths.items()
            },
            "allowed_write_paths": [str(path) for path in self.allowed_write_paths],
            "write_scope_enforced": self.write_scope_enforced,
        }


def require_filesystem_runtime(resources: dict[str, Any]) -> FilesystemRuntimeResource:
    runtime = resources.get("filesystem")
    if not isinstance(runtime, FilesystemRuntimeResource):
        raise RuntimeError("owned filesystem runtime resource is not configured")
    return runtime


def _filesystem_context(resources: dict[str, Any]) -> FilesystemRuntimeResource | dict[str, Any]:
    value = resources.get("filesystem")
    if isinstance(value, FilesystemRuntimeResource):
        return value
    if isinstance(value, dict) and value.get("schema") == "filesystem_runtime_context.v1":
        return value
    raise RuntimeError("filesystem runtime context is not configured")


def required_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def positive_int(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if value < 1:
        raise ValueError(f"{key} must be greater than or equal to 1")
    return value


def filesystem_boundary(resources: dict[str, Any]) -> tuple[Path, bool]:
    runtime = _filesystem_context(resources)
    if isinstance(runtime, FilesystemRuntimeResource):
        return runtime.root, runtime.allow_external
    return Path(str(runtime["root"])).resolve(), bool(runtime.get("allow_external", False))


def filesystem_allowed_roots(resources: dict[str, Any]) -> tuple[Path, ...]:
    runtime = _filesystem_context(resources)
    if isinstance(runtime, FilesystemRuntimeResource):
        return runtime.allowed_roots
    return tuple(Path(str(value)).resolve() for value in runtime.get("allowed_roots", ()))


def filesystem_mounts(resources: dict[str, Any]) -> dict[str, Path]:
    runtime = _filesystem_context(resources)
    if isinstance(runtime, FilesystemRuntimeResource):
        return dict(runtime.mounts)
    return {}


def resolve_path(
    *,
    path: str,
    root: Path,
    allow_external: bool,
    allowed_roots: tuple[Path, ...] = (),
) -> Path:
    candidate = workspace_path_candidate(path, root=root)
    resolved = candidate.resolve(strict=False)
    if allow_external:
        return resolved
    if _path_is_within(resolved, root):
        return resolved
    if any(_path_is_within(resolved, allowed_root) for allowed_root in allowed_roots):
        return resolved
    raise ValueError(f"path escapes filesystem root: {path}")


def path_type(path: Path) -> str:
    if path.is_file():
        return "file"
    if path.is_dir():
        return "directory"
    return "other"


def path_risk_result(
    arguments: dict[str, Any],
    context: dict[str, Any],
    *,
    path_key: str = "path",
    default_action: str,
    sensitive_action: str,
) -> dict[str, Any]:
    path_value = arguments.get(path_key) or "."
    if not isinstance(path_value, str) or not path_value.strip():
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[f"{path_key} must be a non-empty string"],
        ).model_dump(mode="json")
    tool_resources = dict(context.get("resources") or {})
    root, allow_external = filesystem_boundary(tool_resources)
    try:
        resolved = resolve_path(
            path=path_value,
            root=root,
            allow_external=allow_external,
            allowed_roots=filesystem_allowed_roots(tool_resources),
        )
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[
                f"path is outside the configured filesystem boundary: {exc}",
                _workspace_path_guidance(root),
            ],
            facts={"path": path_value, "filesystem_root": str(root)},
        ).model_dump(mode="json")
    is_write_like = default_action != "allow"
    managed_path = _managed_path_spec(resolved, root=root, resources=tool_resources)
    managed_write_path = _managed_write_path_spec(resolved, root=root, resources=tool_resources) if is_write_like else None
    protected = (
        managed_path is not None
        or managed_write_path is not None
        or _is_protected_write_path(resolved, root=root, resources=tool_resources)
    )
    if protected:
        tool_key = "write_tool" if is_write_like else "read_tool"
        path_spec = managed_write_path or managed_path or {}
        dedicated_tool = str(path_spec.get(tool_key) or path_spec.get("tool") or "").strip()
        reason = (
            "path is managed by a dedicated control tool and cannot be modified through generic filesystem tools"
            if is_write_like
            else "path is managed by a dedicated control tool and cannot be read through generic filesystem tools"
        )
        suggested_action = (
            f"Use {dedicated_tool} to update this managed file."
            if dedicated_tool
            else "Use the dedicated control tool to update this managed file."
        ) if is_write_like else (
            f"Use {dedicated_tool} to inspect this managed file."
            if dedicated_tool
            else "Use the dedicated control tool to inspect this managed file."
        )
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[reason, suggested_action],
            facts={
                "path": path_value,
                "resolved_path": str(resolved),
                "filesystem_root": str(root),
                "managed_file_operation": "write" if is_write_like else "read",
                "dedicated_tool": dedicated_tool,
            },
        ).model_dump(mode="json")
    if is_write_like and _is_read_only_write_path(resolved, root=root, resources=tool_resources):
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=["path is read-only runtime input and cannot be modified through generic filesystem tools"],
            facts={
                "path": path_value,
                "resolved_path": str(resolved),
                "filesystem_root": str(root),
                "read_only_runtime_input": True,
            },
        ).model_dump(mode="json")
    if is_write_like and not _is_allowed_write_path(resolved, root=root, resources=tool_resources):
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[
                "path is outside configured allowed_write_paths",
                _workspace_path_guidance(root),
            ],
            facts={
                "path": path_value,
                "resolved_path": str(resolved),
                "filesystem_root": str(root),
            },
        ).model_dump(mode="json")
    focus_facts = _focus_write_facts(resolved, root=root, resources=tool_resources) if is_write_like else {}
    sensitive = _is_sensitive_path(resolved)
    reasons = []
    action = default_action
    risk_level = "low"
    if sensitive:
        action = sensitive_action
        risk_level = "medium"
        reasons.append("path targets a sensitive file or directory")
    return ToolRiskResult(
        action=action,
        risk_level=risk_level,
        reasons=reasons,
        facts={
            "path": path_value,
            "resolved_path": str(resolved),
            "filesystem_root": str(root),
            "sensitive_path": sensitive,
            **focus_facts,
        },
    ).model_dump(mode="json")


def assert_not_protected_write_path(path: Path, *, root: Path, resources: dict[str, Any]) -> None:
    if _managed_write_path_spec(path, root=root, resources=resources) is not None:
        raise PermissionError(f"path is managed by a dedicated write tool: {path}")
    if _is_protected_write_path(path, root=root, resources=resources):
        raise PermissionError(f"path is managed by a dedicated control tool: {path}")
    if _is_read_only_write_path(path, root=root, resources=resources):
        raise PermissionError(f"path is read-only runtime input: {path}")
    if not _is_allowed_write_path(path, root=root, resources=resources):
        raise PermissionError(f"path is outside configured allowed_write_paths: {path}")


def write_focus_facts(path: Path, *, root: Path, resources: dict[str, Any]) -> dict[str, Any]:
    return _focus_write_facts(path, root=root, resources=resources)


def _is_sensitive_path(path: Path) -> bool:
    if path.name in SENSITIVE_FILE_NAMES:
        return True
    return any(part in SENSITIVE_DIR_NAMES for part in path.parts)


def _is_protected_write_path(path: Path, *, root: Path, resources: dict[str, Any]) -> bool:
    for resolved in _context_paths(resources, "protected_write_paths"):
        if path == resolved or resolved in path.parents:
            return True
    return False


def _is_read_only_write_path(path: Path, *, root: Path, resources: dict[str, Any]) -> bool:
    return _path_matches_focus_files(
        path,
        focus_files=_context_paths(resources, "read_only_paths"),
    )


def _managed_path_spec(path: Path, *, root: Path, resources: dict[str, Any]) -> dict[str, Any] | None:
    spec = _context_mapping(resources, "managed_paths").get(path)
    return dict(spec) if spec is not None else None


def _managed_write_path_spec(path: Path, *, root: Path, resources: dict[str, Any]) -> dict[str, Any] | None:
    for resolved, spec in _context_mapping(resources, "managed_write_paths").items():
        if path == resolved or resolved in path.parents:
            return dict(spec)
    return None


def _is_allowed_write_path(path: Path, *, root: Path, resources: dict[str, Any]) -> bool:
    values = _context_paths(resources, "allowed_write_paths")
    runtime = _filesystem_context(resources)
    enforced = (
        runtime.write_scope_enforced
        if isinstance(runtime, FilesystemRuntimeResource)
        else bool(runtime.get("write_scope_enforced", False))
    )
    if not enforced:
        return True
    return _path_matches_focus_files(path, focus_files=values)


def _path_matches_focus_files(path: Path, *, focus_files: tuple[Path, ...]) -> bool:
    if not focus_files:
        return False
    for resolved in focus_files:
        if path == resolved or resolved in path.parents:
            return True
    return False


def _context_paths(resources: dict[str, Any], field_name: str) -> tuple[Path, ...]:
    runtime = _filesystem_context(resources)
    if isinstance(runtime, FilesystemRuntimeResource):
        return tuple(getattr(runtime, field_name))
    values = runtime.get(field_name, ())
    if not isinstance(values, list):
        raise ValueError(f"filesystem runtime context {field_name} must be an array")
    return tuple(Path(str(value)).resolve() for value in values)


def _context_mapping(
    resources: dict[str, Any],
    field_name: str,
) -> dict[Path, Mapping[str, Any]]:
    runtime = _filesystem_context(resources)
    if isinstance(runtime, FilesystemRuntimeResource):
        return dict(getattr(runtime, field_name))
    values = runtime.get(field_name, {})
    if not isinstance(values, dict):
        raise ValueError(f"filesystem runtime context {field_name} must be an object")
    return {
        Path(str(path)).resolve(): dict(spec)
        for path, spec in values.items()
        if isinstance(spec, dict)
    }


def _focus_write_facts(path: Path, *, root: Path, resources: dict[str, Any]) -> dict[str, Any]:
    return {"relative_path": _relative_path_text(path, root=root)}


def _relative_path_text(path: Path, *, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _workspace_path_guidance(root: Path) -> str:
    return (
        "Use a relative path inside the workspace or an absolute path under "
        f"filesystem root {root}; do not use /tmp, host paths, or arbitrary absolute paths "
        "unless external paths are explicitly enabled."
    )
