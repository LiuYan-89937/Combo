from __future__ import annotations

from typing import Any, Protocol

from agent_factory.context_system.compression import estimate_text_tokens
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
        factory_values: dict[str, Any] | None = None,
    ) -> None:
        self.state = state
        self.messages = list(messages or [])
        self.services = services
        self.resources = dict(resources or {})
        self.factory_values = dict(factory_values or {})


class CrossSessionMemorySource:
    source_id = "cross_session_memory"

    def retrieve(self, *, query: ContextQuery, runtime_context: ContextSourceRuntime) -> list[ContextCandidate]:
        memory_system = getattr(runtime_context.services, "memory_system", None) if runtime_context.services else None
        if memory_system is None or not getattr(getattr(memory_system, "config", None), "enabled", False):
            return []
        pack = memory_system.retrieve_context(query=query.text)
        candidates: list[ContextCandidate] = []
        for item in pack.items:
            candidates.append(
                ContextCandidate(
                    candidate_id=f"memory:{item.memory_id}",
                    source_id=self.source_id,
                    kind="memory",
                    content=item.content,
                    score=item.score,
                    token_estimate=estimate_text_tokens(item.content),
                    metadata={
                        "memory_id": item.memory_id,
                        "memory_type": item.memory_type,
                        "kind": item.kind,
                        "namespace": list(item.namespace),
                    },
                )
            )
        return candidates


class ResourcesSource:
    source_id = "resources"

    def retrieve(self, *, query: ContextQuery, runtime_context: ContextSourceRuntime) -> list[ContextCandidate]:
        resources = runtime_context.resources
        if not resources:
            resources = dict(getattr(runtime_context.services, "runtime_resources", {}) or {})
        candidates: list[ContextCandidate] = []
        for key, value in sorted(resources.items())[:24]:
            text = f"{key}: {_safe_preview(value)}"
            candidates.append(
                ContextCandidate(
                    candidate_id=f"resource:{key}",
                    source_id=self.source_id,
                    kind="resource",
                    content=text,
                    score=0.45,
                    token_estimate=estimate_text_tokens(text),
                    metadata={"resource_key": key},
                )
            )
        return candidates


class SchedulerContextSource:
    source_id = "scheduler"

    def retrieve(self, *, query: ContextQuery, runtime_context: ContextSourceRuntime) -> list[ContextCandidate]:
        scheduler_runtime = getattr(runtime_context.services, "scheduler_runtime", None) if runtime_context.services else None
        if scheduler_runtime is None:
            return []
        config = getattr(scheduler_runtime, "config", None)
        owner_id = str(getattr(scheduler_runtime, "owner_id", "") or "")
        text = f"scheduler enabled for {owner_id}" if owner_id else "scheduler enabled"
        if config is not None:
            text += f"; timezone={getattr(config, 'timezone', '')}; unattended_policy={getattr(config, 'unattended_policy', '')}"
        return [
            ContextCandidate(
                candidate_id="scheduler:runtime",
                source_id=self.source_id,
                kind="scheduler",
                content=text,
                score=0.35,
                token_estimate=estimate_text_tokens(text),
            )
        ]


class EmptyContextSource:
    def __init__(self, source_id: str) -> None:
        self.source_id = source_id

    def retrieve(self, *, query: ContextQuery, runtime_context: ContextSourceRuntime) -> list[ContextCandidate]:
        return []


def default_context_sources() -> dict[str, ContextSource]:
    return {
        "cross_session_memory": CrossSessionMemorySource(),
        "resources": ResourcesSource(),
        "artifacts": EmptyContextSource("artifacts"),
        "scheduler": SchedulerContextSource(),
        "knowledge": EmptyContextSource("knowledge"),
        "trace": EmptyContextSource("trace"),
    }


def _safe_preview(value: Any) -> str:
    text = str(value)
    return text if len(text) <= 180 else text[:177] + "..."
