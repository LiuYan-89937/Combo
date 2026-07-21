from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.runtime_workspace import (
    RUNTIME_OUTPUT_ROOT_SESSION_KEY,
    RUNTIME_WORKSPACE_ROOT_SESSION_KEY,
    SESSION_OUTPUT_DIR,
)


def apply_runtime_workspace(
    session_config: dict[str, Any],
    payload: dict[str, Any],
    *,
    workdir_root: Path,
) -> None:
    workspace = payload.get("runtime_workspace")
    if not isinstance(workspace, dict):
        return
    scope = str(workspace.get("scope") or "").strip()
    relative = Path(scope)
    if relative.is_absolute():
        raise ValueError("runtime workspace scope must be relative")
    root = workdir_root.expanduser().resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"runtime workspace scope escapes package workdir: {scope}") from exc
    target.mkdir(parents=True, exist_ok=True)
    output_root = target / SESSION_OUTPUT_DIR
    output_root.mkdir(parents=True, exist_ok=True)
    session_config["builtin_workspace_root"] = str(target)
    session_config[RUNTIME_WORKSPACE_ROOT_SESSION_KEY] = str(target)
    session_config[RUNTIME_OUTPUT_ROOT_SESSION_KEY] = str(output_root)
