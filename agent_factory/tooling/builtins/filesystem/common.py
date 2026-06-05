from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.tooling.spec import ToolRiskResult


SENSITIVE_FILE_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519"}
SENSITIVE_DIR_NAMES = {".ssh", ".gnupg", "secrets", "secret", "credentials"}


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
    config = resources.get("filesystem", {})
    if isinstance(config, str):
        root_value: Any = config
        allow_external = False
    elif isinstance(config, dict):
        root_value = config.get("root") or config.get("cwd") or "."
        allow_external = bool(config.get("allow_external", False))
    else:
        root_value = "."
        allow_external = False
    root = Path(str(root_value)).expanduser().resolve()
    return root, allow_external


def resolve_path(*, path: str, root: Path, allow_external: bool) -> Path:
    requested = Path(path).expanduser()
    candidate = requested if requested.is_absolute() else root / requested
    resolved = candidate.resolve(strict=False)
    if allow_external:
        return resolved
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes filesystem root: {path}") from exc
    return resolved


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
        resolved = resolve_path(path=path_value, root=root, allow_external=allow_external)
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[f"path is outside the configured filesystem boundary: {exc}"],
            facts={"path": path_value, "filesystem_root": str(root)},
        ).model_dump(mode="json")
    managed_path = _managed_path_spec(resolved, root=root, resources=tool_resources)
    protected = managed_path is not None or _is_protected_write_path(resolved, root=root, resources=tool_resources)
    if protected:
        is_write_like = default_action != "allow"
        tool_key = "write_tool" if is_write_like else "read_tool"
        dedicated_tool = str((managed_path or {}).get(tool_key) or (managed_path or {}).get("tool") or "").strip()
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
        },
    ).model_dump(mode="json")


def assert_not_protected_write_path(path: Path, *, root: Path, resources: dict[str, Any]) -> None:
    if _is_protected_write_path(path, root=root, resources=resources):
        raise PermissionError(f"path is managed by a dedicated control tool: {path}")


def _is_sensitive_path(path: Path) -> bool:
    if path.name in SENSITIVE_FILE_NAMES:
        return True
    return any(part in SENSITIVE_DIR_NAMES for part in path.parts)


def _is_protected_write_path(path: Path, *, root: Path, resources: dict[str, Any]) -> bool:
    config = resources.get("filesystem", {})
    values = config.get("protected_write_paths", []) if isinstance(config, dict) else []
    if not isinstance(values, list):
        return False
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        requested = Path(value).expanduser()
        candidate = requested if requested.is_absolute() else root / requested
        if path == candidate.resolve(strict=False):
            return True
    return False


def _managed_path_spec(path: Path, *, root: Path, resources: dict[str, Any]) -> dict[str, Any] | None:
    config = resources.get("filesystem", {})
    values = config.get("managed_paths", {}) if isinstance(config, dict) else {}
    if not isinstance(values, dict):
        return None
    for raw_path, raw_spec in values.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        requested = Path(raw_path).expanduser()
        candidate = requested if requested.is_absolute() else root / requested
        if path != candidate.resolve(strict=False):
            continue
        return raw_spec if isinstance(raw_spec, dict) else {}
    return None
