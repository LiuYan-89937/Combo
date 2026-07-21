from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_factory.runtime_attachments import ATTACHMENT_INPUT_DIR
from agent_factory.runtime_workspace import (
    RUNTIME_OUTPUT_ROOT_SESSION_KEY,
    RUNTIME_WORKSPACE_ROOT_SESSION_KEY,
    SESSION_OUTPUT_DIR,
)


PACKAGE_TOOL_SYSTEM_RESOURCE_IDS = frozenset(
    {"artifacts_root", "package_root", "runtime_root", "workdir_root", "workspace_root"}
)


def runtime_resource_overrides_from_state(state: Any) -> dict[str, Any]:
    runtime_config = _runtime_config_from_state(state)
    session_config = (
        runtime_config.get("session_config", {})
        if isinstance(runtime_config, Mapping)
        else getattr(runtime_config, "session_config", {})
    )
    if not isinstance(session_config, dict):
        return {}
    root = str(session_config.get(RUNTIME_WORKSPACE_ROOT_SESSION_KEY) or "").strip()
    if not root:
        return {}
    output_root = str(session_config.get(RUNTIME_OUTPUT_ROOT_SESSION_KEY) or "").strip()
    if not output_root:
        output_root = str(Path(root) / SESSION_OUTPUT_DIR)
    read_only_input = str(Path(root) / ATTACHMENT_INPUT_DIR)
    workspace_boundary = {
        "root": root,
        "read_only_paths": [read_only_input],
    }
    return {
        "filesystem": dict(workspace_boundary),
        "process_runtime": dict(workspace_boundary),
        "artifacts_root": output_root,
        "workdir_root": root,
        "workspace_root": root,
    }


def _runtime_config_from_state(state: Any) -> Any:
    if not isinstance(state, Mapping):
        return getattr(state, "runtime_config", None)
    runtime = state.get("runtime")
    if isinstance(runtime, Mapping):
        return runtime.get("runtime_config")
    return state.get("runtime_config")


def merge_runtime_resource(base: Any, override: Any) -> Any:
    if not isinstance(base, Mapping) or not isinstance(override, Mapping):
        return override
    merged = dict(base)
    for key, value in override.items():
        if key == "read_only_paths" and isinstance(merged.get(key), list) and isinstance(value, list):
            merged[key] = list(dict.fromkeys([*merged[key], *value]))
            continue
        if key in merged and isinstance(merged[key], Mapping) and isinstance(value, Mapping):
            merged[key] = merge_runtime_resource(merged[key], value)
            continue
        merged[key] = value
    return merged


def resolve_resource_selector(resources: Mapping[str, Any], selector: str) -> Any:
    current: Any = resources
    for part in selector.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise KeyError(selector)
        current = current[part]
    return current
