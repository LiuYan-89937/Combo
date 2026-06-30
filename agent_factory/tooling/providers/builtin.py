from __future__ import annotations

from collections.abc import Iterable

from agent_factory.tooling.builtins import (
    get_always_available_system_tool_ids,
    get_builtin_tool_ids,
    get_builtin_tool_specs,
)
from agent_factory.tooling.providers.base import ToolProviderContext, ToolProviderResult
from agent_factory.runtime_attachments import ATTACHMENT_INPUT_DIR
from agent_factory.runtime_defaults import (
    DEFAULT_BUILTIN_ALLOW_EXTERNAL_PATHS,
    DEFAULT_BUILTIN_WORKSPACE_ROOT,
)


class BuiltinToolProvider:
    provider_id = "builtin"

    def __init__(self, *, tool_ids: Iterable[str] | None = None) -> None:
        self._tool_ids = set(tool_ids or [])

    def discover(self, context: ToolProviderContext) -> ToolProviderResult:
        known_ids = set(get_builtin_tool_ids())
        unknown_ids = sorted(self._tool_ids - known_ids)
        if unknown_ids:
            raise ValueError("unknown builtin tool ids: " + ", ".join(unknown_ids))
        specs = get_builtin_tool_specs()
        if self._tool_ids:
            always_available = get_always_available_system_tool_ids()
            specs = [spec for spec in specs if spec.id in self._tool_ids or spec.id in always_available]
        return ToolProviderResult(
            tool_specs=specs,
            system_tool_ids=[spec.id for spec in specs],
            runtime_resources=_runtime_resources(context),
        )


def _runtime_resources(context: ToolProviderContext) -> dict[str, object]:
    resources = dict(context.resources)
    root = str(resources.get("builtin_workspace_root") or DEFAULT_BUILTIN_WORKSPACE_ROOT)
    allow_external = bool(resources.get("builtin_allow_external_paths", DEFAULT_BUILTIN_ALLOW_EXTERNAL_PATHS))
    read_only_paths = _read_only_paths(resources, root=root)
    return {
        "filesystem": {
            "root": root,
            "allow_external": allow_external,
            "read_only_paths": read_only_paths,
        },
        "process_runtime": {
            "root": root,
            "allow_external": allow_external,
            "read_only_paths": read_only_paths,
        },
    }


def _read_only_paths(resources: dict[str, object], *, root: str) -> list[str]:
    configured = resources.get("builtin_read_only_paths")
    values = (
        [str(item) for item in configured if isinstance(item, str) and item.strip()]
        if isinstance(configured, list)
        else []
    )
    default_input_path = f"{root.rstrip('/')}/{ATTACHMENT_INPUT_DIR}"
    return [*values, default_input_path]
