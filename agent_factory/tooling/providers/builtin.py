from __future__ import annotations

from collections.abc import Iterable

from agent_factory.tooling.builtins import get_builtin_tool_specs
from agent_factory.tooling.providers.base import ToolProviderContext, ToolProviderResult


class BuiltinToolProvider:
    provider_id = "builtin"

    def __init__(self, *, tool_ids: Iterable[str] | None = None) -> None:
        self._tool_ids = set(tool_ids or [])

    def discover(self, context: ToolProviderContext) -> ToolProviderResult:
        specs = get_builtin_tool_specs()
        if self._tool_ids:
            specs = [spec for spec in specs if spec.id in self._tool_ids]
        return ToolProviderResult(tool_specs=specs)
