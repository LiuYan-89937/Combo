from __future__ import annotations

from typing import Any, Protocol

from agent_factory.context_system.schema import ContextCandidate, ContextQuery


class ContextSource(Protocol):
    source_id: str

    def retrieve(self, *, query: ContextQuery, runtime_context: "ContextSourceRuntime") -> list[ContextCandidate]:
        ...


class ContextSourceRuntime:
    def __init__(
        self,
        *,
        state: Any = None,
        messages: list[Any] | None = None,
        services: Any = None,
        resources: dict[str, Any] | None = None,
    ) -> None:
        self.state = state
        self.messages = list(messages or [])
        self.services = services
        self.resources = dict(resources or {})


def default_context_sources() -> dict[str, ContextSource]:
    return {}
