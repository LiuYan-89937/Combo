from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from agent_factory.tooling.builtins.filesystem.common import (
    filesystem_boundary,
    path_risk_result,
    positive_int,
    required_string,
    resolve_path,
)


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
_TEXT_SUFFIXES = {
    "",
    ".bash",
    ".c",
    ".cfg",
    ".conf",
    ".css",
    ".csv",
    ".dockerfile",
    ".env",
    ".go",
    ".h",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".lock",
    ".log",
    ".md",
    ".mjs",
    ".py",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
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
    include = arguments.get("include")
    if include is not None and not isinstance(include, str):
        raise ValueError("include must be a string")
    case_sensitive = bool(arguments.get("case_sensitive", True))
    use_regex = bool(arguments.get("regex", True))
    max_results = positive_int(arguments.get("max_results", 100), "max_results")
    if max_results > 5000:
        raise ValueError("max_results must be less than or equal to 5000")
    matcher = _compile_matcher(pattern=pattern, case_sensitive=case_sensitive, use_regex=use_regex)
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(path=base_path, root=root, allow_external=allow_external)
    if not target.exists():
        raise FileNotFoundError(str(target))
    paths = [target] if target.is_file() else _iter_files(target)
    matches: list[dict[str, Any]] = []
    truncated = False
    for file_path in paths:
        if include and not fnmatch.fnmatch(file_path.name, include) and not fnmatch.fnmatch(str(file_path), include):
            continue
        if not _looks_text(file_path):
            continue
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if not matcher(line):
                continue
            if len(matches) >= max_results:
                truncated = True
                return {"matches": matches, "truncated": truncated}
            matches.append({"path": str(file_path), "line": line, "line_number": line_number})
    return {"matches": matches, "truncated": truncated}


def _compile_matcher(*, pattern: str, case_sensitive: bool, use_regex: bool):
    if use_regex:
        flags = 0 if case_sensitive else re.IGNORECASE
        compiled = re.compile(pattern, flags=flags)
        return lambda line: bool(compiled.search(line))
    needle = pattern if case_sensitive else pattern.lower()
    return lambda line: needle in (line if case_sensitive else line.lower())


def _iter_files(root: Path) -> list[Path]:
    return sorted(
        (path for path in root.rglob("*") if path.is_file() and not _is_skipped(path)),
        key=lambda item: str(item),
    )


def _is_skipped(path: Path) -> bool:
    return any(part in _SKIPPED_DIR_NAMES for part in path.parts)


def _looks_text(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_SUFFIXES
