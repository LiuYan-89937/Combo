from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.tooling.builtins.filesystem.common import (
    filesystem_boundary,
    path_type,
    positive_int,
    required_string,
    resolve_path,
)


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    path = required_string(arguments, "path")
    recursive = bool(arguments.get("recursive", False))
    max_entries = positive_int(arguments.get("max_entries", 200), "max_entries")
    if max_entries > 5000:
        raise ValueError("max_entries must be less than or equal to 5000")
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(path=path, root=root, allow_external=allow_external)
    if not target.exists():
        raise FileNotFoundError(str(target))
    if not target.is_dir():
        raise NotADirectoryError(str(target))
    paths = _iter_paths(target, recursive=recursive)
    entries: list[dict[str, str]] = []
    truncated = False
    for item in paths:
        if len(entries) >= max_entries:
            truncated = True
            break
        entries.append(
            {
                "path": str(item),
                "name": item.name,
                "type": path_type(item),
            }
        )
    return {"entries": entries, "truncated": truncated}


def _iter_paths(root: Path, *, recursive: bool) -> list[Path]:
    if recursive:
        return sorted(root.rglob("*"), key=lambda item: str(item))
    return sorted(root.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower(), item.name))
