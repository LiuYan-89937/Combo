from __future__ import annotations

from hashlib import sha256
from typing import Any

from agent_factory.tooling.builtins.filesystem.common import (
    filesystem_boundary,
    path_risk_result,
    positive_int,
    required_string,
    resolve_path,
)


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return path_risk_result(arguments, context, default_action="allow", sensitive_action="ask")


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    path = required_string(arguments, "path")
    start_line = positive_int(arguments.get("start_line", 1), "start_line")
    limit = positive_int(arguments.get("limit", 200), "limit")
    if limit > 2000:
        raise ValueError("limit must be less than or equal to 2000")
    root, allow_external = filesystem_boundary(resources)
    target = resolve_path(path=path, root=root, allow_external=allow_external)
    if not target.exists():
        raise FileNotFoundError(str(target))
    if not target.is_file():
        raise IsADirectoryError(str(target))
    raw = target.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"file is not valid utf-8 text: {target}") from exc
    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    start_index = start_line - 1
    end_index = min(start_index + limit, total_lines)
    selected = lines[start_index:end_index] if start_index < total_lines else []
    end_line = start_line + len(selected) - 1 if selected else max(start_line - 1, 0)
    return {
        "path": str(target),
        "content": "".join(selected),
        "start_line": start_line,
        "end_line": end_line,
        "total_lines": total_lines,
        "truncated": end_index < total_lines,
        "content_hash": sha256(raw).hexdigest(),
    }
