from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from agent_factory.context_system.schema import ContextCandidate, ContextQuery
from agent_factory.context_system.token_estimation import estimate_text_tokens
from agent_factory.runtime_protocol import RuntimeExecutionIdentity


class ScopedMemorySearchStore(Protocol):
    def search(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        query: str,
        limit: int,
    ) -> tuple[Any, ...]:
        ...


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
        resources: Mapping[str, Any] | None = None,
    ) -> None:
        self.state = state
        self.messages = list(messages or [])
        self.services = services
        self.resources = dict(resources or {})


class ScopedMemoryContextSource:
    source_id = "cross_session_memory"

    def __init__(self, store: ScopedMemorySearchStore) -> None:
        self._store = store

    def retrieve(
        self,
        *,
        query: ContextQuery,
        runtime_context: ContextSourceRuntime,
    ) -> list[ContextCandidate]:
        identity = runtime_context.resources.get("runtime_identity")
        if not isinstance(identity, RuntimeExecutionIdentity):
            raise RuntimeError("memory context retrieval requires runtime identity")
        results = self._store.search(
            principal_id=identity.principal_id,
            workspace_id=identity.workspace_id,
            query=query.text,
            limit=64,
        )
        return [
            ContextCandidate(
                candidate_id=f"memory:{item.revision.memory_id}:{item.revision.revision}",
                source_id=self.source_id,
                kind="memory",
                content=item.revision.content,
                score=item.score,
                token_estimate=estimate_text_tokens(item.revision.content),
                metadata={
                    "memory_id": item.revision.memory_id,
                    "revision": item.revision.revision,
                    "scope": item.revision.scope,
                    "memory_kind": item.revision.kind,
                    "content_digest": item.revision.content_digest,
                },
            )
            for item in results
        ]


def default_context_sources(memory_store: ScopedMemorySearchStore) -> dict[str, ContextSource]:
    source = ScopedMemoryContextSource(memory_store)
    return {source.source_id: source}
