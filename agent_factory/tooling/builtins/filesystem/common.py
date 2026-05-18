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


def _is_sensitive_path(path: Path) -> bool:
    if path.name in SENSITIVE_FILE_NAMES:
        return True
    return any(part in SENSITIVE_DIR_NAMES for part in path.parts)
