from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from hashlib import sha256
from typing import Any, Protocol

from combo.context_system.schema import ContextCandidate, ContextQuery
from combo.context_system.token_estimation import estimate_text_tokens
from combo.runtime_protocol import RuntimeExecutionIdentity


class ScopedMemorySearchStore(Protocol):
    def search(self, *, principal_id: str, workspace_id: str, query: str, limit: int,
               min_relevance: float = 0.0) -> tuple[Any, ...]: ...
    def search_version(self, *, principal_id: str, workspace_id: str) -> str: ...
    def active_references(self, *, principal_id: str, workspace_id: str) -> dict[str, tuple[int, str]]: ...


class ContextSource(Protocol):
    source_id: str
    def retrieve(self, *, query: ContextQuery, runtime_context: "ContextSourceRuntime") -> list[ContextCandidate]: ...
    def version(self, *, runtime_context: "ContextSourceRuntime") -> str: ...
    def validate(self, candidates: list[ContextCandidate], *, runtime_context: "ContextSourceRuntime") -> list[ContextCandidate]: ...


class ContextSourceRuntime:
    def __init__(self, *, state: Any = None, resources: Mapping[str, Any] | None = None) -> None:
        self.state = state
        self.resources = dict(resources or {})

    def memory_identity(self) -> RuntimeExecutionIdentity:
        identity = self.resources.get("runtime_identity")
        if not isinstance(identity, RuntimeExecutionIdentity):
            raise RuntimeError("memory context requires an owned runtime identity")
        run = getattr(self.state, "run", None)
        if run is not None and (run.runtime_instance_id != identity.runtime_instance_id
                                or run.workspace_id != identity.workspace_id
                                or run.session_id != identity.session_id):
            raise RuntimeError("memory context identity differs from active runtime")
        return identity


class ScopedMemoryContextSource:
    source_id = "cross_session_memory"

    def __init__(self, store: ScopedMemorySearchStore) -> None:
        self._store = store

    def version(self, *, runtime_context: ContextSourceRuntime) -> str:
        identity = runtime_context.memory_identity()
        return self._store.search_version(principal_id=identity.principal_id, workspace_id=identity.workspace_id)

    def retrieve(self, *, query: ContextQuery, runtime_context: ContextSourceRuntime) -> list[ContextCandidate]:
        identity = runtime_context.memory_identity()
        results = self._store.search(
            principal_id=identity.principal_id, workspace_id=identity.workspace_id,
            query=query.text, limit=query.limit, min_relevance=query.min_relevance,
        )
        return [memory_candidate(item) for item in results]

    def validate(self, candidates: list[ContextCandidate], *, runtime_context: ContextSourceRuntime) -> list[ContextCandidate]:
        identity = runtime_context.memory_identity()
        refs = self._store.active_references(principal_id=identity.principal_id, workspace_id=identity.workspace_id)
        return [item for item in candidates
                if item.source_id == self.source_id
                and item.metadata.get("principal_id") == identity.principal_id
                and refs.get(item.metadata.get("memory_id")) == (
                    item.metadata.get("revision"), sha256(item.content.encode()).hexdigest(),
                )]


def memory_candidate(result: Any, *, origin: str = "automatic") -> ContextCandidate:
    revision = result.revision
    return ContextCandidate(
        candidate_id=f"memory:{revision.memory_id}:{revision.revision}",
        source_id="cross_session_memory", kind="memory", content=revision.content,
        score=result.score, relevance=result.relevance,
        token_estimate=estimate_text_tokens(revision.content),
        metadata={
            "memory_id": revision.memory_id, "revision": revision.revision,
            "principal_id": revision.principal_id, "scope": revision.scope,
            "workspace_id": revision.workspace_id, "memory_kind": revision.kind,
            "content_digest": revision.content_digest, "confidence": revision.confidence,
            "source_session_id": revision.source_session_id, "source_turn_id": revision.source_turn_id,
            "created_at": revision.created_at, "retrieval_origin": origin,
            "retrieval_evidence": [asdict(item) for item in result.evidence],
        },
    )


def default_context_sources(memory_store: ScopedMemorySearchStore) -> dict[str, ContextSource]:
    source = ScopedMemoryContextSource(memory_store)
    return {source.source_id: source}
