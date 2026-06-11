from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.tooling.builtins.filesystem.common import (
    filesystem_boundary,
    path_risk_result,
    path_type,
    positive_int,
    required_string,
    resolve_path,
)
from agent_factory.tooling.envelope import tool_envelope


_SKIPPED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return path_risk_result(
        arguments,
        context,
        path_key="base_path",
        default_action="allow",
        sensitive_action="ask",
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    pattern = required_string(arguments, "pattern")
    base_path = str(arguments.get("base_path") or ".")
    max_results = positive_int(arguments.get("max_results", 100), "max_results")
    if max_results > 5000:
        raise ValueError("max_results must be less than or equal to 5000")
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(path=base_path, root=root, allow_external=allow_external)
    if not target.exists():
        raise FileNotFoundError(str(target))
    if not target.is_dir():
        raise NotADirectoryError(str(target))
    matches: list[dict[str, str]] = []
    truncated = False
    for item in _glob_paths(target, pattern):
        if len(matches) >= max_results:
            truncated = True
            break
        matches.append(
            {
                "path": str(item),
                "name": item.name,
                "type": path_type(item),
            }
        )
    return tool_envelope({"matches": matches, "truncated": truncated})


def _glob_paths(root: Path, pattern: str) -> list[Path]:
    return sorted(
        (path for path in root.glob(pattern) if not _is_skipped(path)),
        key=lambda item: (not item.is_dir(), str(item)),
    )


def _is_skipped(path: Path) -> bool:
    return any(part in _SKIPPED_DIR_NAMES for part in path.parts)
