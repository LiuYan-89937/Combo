from __future__ import annotations

from collections.abc import Iterable

from agent_factory.tooling.builtins import get_builtin_tool_ids, get_builtin_tool_specs
from agent_factory.tooling.providers.base import ToolProviderContext, ToolProviderResult


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
            specs = [spec for spec in specs if spec.id in self._tool_ids]
        return ToolProviderResult(
            tool_specs=specs,
            system_tool_ids=[spec.id for spec in specs],
            runtime_resources=_runtime_resources(context),
        )


def _runtime_resources(context: ToolProviderContext) -> dict[str, object]:
    resources = dict(context.resources)
    root = str(resources.get("builtin_workspace_root") or "/workdir")
    allow_external = bool(resources.get("builtin_allow_external_paths", False))
    return {
        "filesystem": {
            "root": root,
            "allow_external": allow_external,
        },
        "process_runtime": {
            "root": root,
            "allow_external": allow_external,
        },
    }
