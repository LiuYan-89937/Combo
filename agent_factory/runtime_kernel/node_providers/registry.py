from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.nodes.base import NodeImplementation


class NodeProvider(Protocol):
    provider_id: str

    def implementations(self) -> list[NodeImplementation]:
        ...


@dataclass(frozen=True, slots=True)
class StaticNodeProvider:
    provider_id: str
    nodes: tuple[NodeImplementation, ...]

    def implementations(self) -> list[NodeImplementation]:
        return list(self.nodes)


class NodeProviderRegistry:
    def __init__(self, providers: list[NodeProvider] | tuple[NodeProvider, ...] | None = None) -> None:
        self._providers: dict[str, NodeProvider] = {}
        for provider in providers or ():
            self.register(provider)

    def register(self, provider: NodeProvider) -> None:
        provider_id = str(provider.provider_id).strip()
        if not provider_id:
            raise RuntimeKernelError("node provider id must not be empty")
        if provider_id in self._providers:
            raise RuntimeKernelError(f"duplicate node provider id: {provider_id}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> NodeProvider:
        if provider_id not in self._providers:
            raise RuntimeKernelError(f"unknown node provider id: {provider_id}")
        return self._providers[provider_id]

    def resolve_many(self, provider_ids: list[str] | tuple[str, ...]) -> list[NodeProvider]:
        return [self.get(provider_id) for provider_id in provider_ids]

    def list_provider_ids(self) -> list[str]:
        return sorted(self._providers)
