from __future__ import annotations

from pathlib import Path
from typing import Mapping

from agent_factory.tooling.entrypoints import (
    EntrypointAdapterError,
    EntrypointAdapterRegistry,
    MCPEntrypointAdapter,
    MCPToolClient,
    PythonEntrypointAdapter,
    ToolEntrypointCallable,
)


class ToolEntrypointError(EntrypointAdapterError):
    pass


class ToolEntrypointLoader:
    """Compatibility facade over the protocol-based entrypoint adapter registry."""

    def __init__(
        self,
        *,
        package_root: str | Path | None = None,
        allowed_python_roots: list[str | Path] | None = None,
        adapter_registry: EntrypointAdapterRegistry | None = None,
        mcp_clients: Mapping[str, MCPToolClient] | None = None,
    ) -> None:
        if adapter_registry is not None:
            self.registry = adapter_registry
        else:
            self.registry = EntrypointAdapterRegistry(
                [
                    MCPEntrypointAdapter(clients=mcp_clients),
                    PythonEntrypointAdapter(package_root=package_root, allowed_roots=allowed_python_roots),
                ]
            )

    def load(self, entrypoint: str) -> ToolEntrypointCallable:
        try:
            return self.registry.load(entrypoint)
        except EntrypointAdapterError as exc:
            raise ToolEntrypointError(str(exc)) from exc
