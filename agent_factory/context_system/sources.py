from __future__ import annotations

from typing import Any, Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_factory.context_system.compression import estimate_text_tokens, is_context_summary_message
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


class RecentMessagesSource:
    source_id = "recent_messages"

    def retrieve(self, *, query: ContextQuery, runtime_context: ContextSourceRuntime) -> list[ContextCandidate]:
        candidates: list[ContextCandidate] = []
        for index, message in enumerate(runtime_context.messages[-8:]):
            if is_context_summary_message(message):
                continue
            content = _message_text(message)
            if not content:
                continue
            candidates.append(
                ContextCandidate(
                    candidate_id=f"recent:{index}",
                    source_id=self.source_id,
                    kind="recent_message",
                    content=f"{_message_role(message)}: {content}",
                    score=0.65,
                    token_estimate=estimate_text_tokens(content),
                )
            )
        return candidates


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


class ToolMetadataSource:
    source_id = "tool_metadata"

    def retrieve(self, *, query: ContextQuery, runtime_context: ContextSourceRuntime) -> list[ContextCandidate]:
        registry = getattr(runtime_context.services, "tool_registry", None) if runtime_context.services else None
        if registry is None or not hasattr(registry, "model_tools"):
            return []
        candidates: list[ContextCandidate] = []
        for tool in registry.model_tools():
            name = str(getattr(tool, "name", "") or "")
            description = str(getattr(tool, "description", "") or "")
            if not name:
                continue
            text = f"{name}: {description}".strip()
            candidates.append(
                ContextCandidate(
                    candidate_id=f"tool:{name}",
                    source_id=self.source_id,
                    kind="tool",
                    content=text,
                    score=0.4,
                    token_estimate=estimate_text_tokens(text),
                    metadata={"tool_id": name},
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
        "recent_messages": RecentMessagesSource(),
        "cross_session_memory": CrossSessionMemorySource(),
        "resources": ResourcesSource(),
        "artifacts": EmptyContextSource("artifacts"),
        "tool_metadata": ToolMetadataSource(),
        "scheduler": SchedulerContextSource(),
        "knowledge": EmptyContextSource("knowledge"),
        "trace": EmptyContextSource("trace"),
    }


def _message_role(message: Any) -> str:
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    if isinstance(message, SystemMessage):
        return "system"
    return str(getattr(message, "type", "message"))


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content.strip()
    return str(content).strip()


def _safe_preview(value: Any) -> str:
    text = str(value)
    return text if len(text) <= 180 else text[:177] + "..."
