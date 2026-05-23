from __future__ import annotations

from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.context_system.assembly import assemble_context_frame
from agent_factory.context_system.compression import estimate_text_tokens, maybe_compress_messages
from agent_factory.context_system.events import emit_context_event
from agent_factory.context_system.schema import (
    ContextCandidate,
    ContextContractConfig,
    ContextInjectionReport,
    ContextPolicy,
    ContextQuery,
    ContextRetrievalReport,
    LLMContextFrame,
)
from agent_factory.context_system.sources import ContextSource, ContextSourceRuntime, default_context_sources


class ContextPreparationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    state: Any
    messages: list[Any] = Field(default_factory=list)
    frame: LLMContextFrame | None = None
    messages_changed: bool = False
    retrieval_report: ContextRetrievalReport
    injection_report: ContextInjectionReport


class ContextSystemRuntime:
    def __init__(
        self,
        *,
        config: ContextContractConfig | None = None,
        sources: dict[str, ContextSource] | None = None,
    ) -> None:
        self.config = config or ContextContractConfig()
        self.sources = sources or default_context_sources()

    def policy_for_node(self, node_id: str) -> ContextPolicy:
        return self.config.node_policies.get(node_id) or self.config.default_policy

    def prepare_before_model_call(
        self,
        *,
        state: Any,
        node_id: str,
        impl: str,
        messages: list[Any],
        services: Any = None,
        resources: dict[str, Any] | None = None,
    ) -> ContextPreparationResult:
        if not self.config.enabled:
            retrieval_report = ContextRetrievalReport(status="skipped", node_id=node_id)
            injection_report = ContextInjectionReport(status="skipped", node_id=node_id)
            return ContextPreparationResult(
                state=state,
                messages=list(messages),
                retrieval_report=retrieval_report,
                injection_report=injection_report,
            )
        policy = self.policy_for_node(node_id)
        working_messages = list(messages)
        working_state = state
        compression_messages, compression_report = maybe_compress_messages(
            messages=working_messages,
            policy=policy.compression,
            node_id=node_id,
        )
        emit_context_event(
            services=services,
            state=working_state,
            event_type="context_compression_completed" if compression_report.status != "failed" else "context_compression_failed",
            node_id=node_id,
            payload=compression_report.model_dump(mode="json"),
        )
        if compression_report.status == "failed":
            raise RuntimeError(compression_report.error or "context compression failed")
        messages_changed = compression_messages != working_messages
        working_messages = compression_messages
        query = self._query_for_state(state=working_state, node_id=node_id, impl=impl, messages=working_messages)
        candidates, retrieval_report = self._retrieve(
            query=query,
            policy=policy,
            runtime_context=ContextSourceRuntime(
                state=working_state,
                messages=working_messages,
                services=services,
                resources=resources or {},
            ),
        )
        frame = assemble_context_frame(
            node_id=node_id,
            query=query,
            candidates=candidates,
            policy=policy.assembly,
        )
        retrieval_report.selected_count = len(frame.items)
        retrieval_report.token_estimate = frame.token_estimate
        injection_report = ContextInjectionReport(
            status="completed",
            node_id=node_id,
            item_count=len(frame.items),
            token_estimate=frame.token_estimate,
        )
        updated = working_state.model_copy(deep=True)
        updated.context.model_context = {
            **updated.context.model_context,
            "llm_context_frame": frame.model_dump(mode="json"),
            node_id: frame.model_dump(mode="json"),
        }
        updated.context.assembly_log.append(f"system_context_prepare:{node_id}")
        emit_context_event(
            services=services,
            state=updated,
            event_type="context_retrieval_completed",
            node_id=node_id,
            payload=retrieval_report.model_dump(mode="json"),
        )
        emit_context_event(
            services=services,
            state=updated,
            event_type="context_assembly_completed",
            node_id=node_id,
            payload=injection_report.model_dump(mode="json"),
        )
        emit_context_event(
            services=services,
            state=updated,
            event_type="context_injection_completed",
            node_id=node_id,
            payload=injection_report.model_dump(mode="json"),
        )
        return ContextPreparationResult(
            state=updated,
            messages=working_messages,
            frame=frame,
            messages_changed=messages_changed,
            retrieval_report=retrieval_report,
            injection_report=injection_report,
        )

    def prepare_factory_values(
        self,
        *,
        stage_id: str,
        values: dict[str, Any],
        services: Any = None,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            return values
        query = ContextQuery(
            node_id=stage_id,
            impl="factory.model_call",
            user_input=str(values.get("user_input") or values.get("requirement") or ""),
            text=_factory_query_text(stage_id=stage_id, values=values),
        )
        policy = self.policy_for_node(stage_id)
        candidates, retrieval_report = self._retrieve(
            query=query,
            policy=policy,
            runtime_context=ContextSourceRuntime(
                services=services,
                factory_values=values,
            ),
        )
        frame = assemble_context_frame(
            node_id=stage_id,
            query=query,
            candidates=candidates,
            policy=policy.assembly,
        )
        emit_context_event(
            services=None,
            state=None,
            event_type="context_retrieval_completed",
            node_id=stage_id,
            payload=retrieval_report.model_dump(mode="json"),
        )
        if not frame.text:
            return values
        return {
            **values,
            "context_frame": frame.model_dump(mode="json"),
            "factory_operating_context": (
                str(values.get("factory_operating_context") or "")
                + "\n\n"
                + frame.text
                + "\nUse this context only when it is directly relevant."
            ).strip(),
        }

    def _retrieve(
        self,
        *,
        query: ContextQuery,
        policy: ContextPolicy,
        runtime_context: ContextSourceRuntime,
    ) -> tuple[list[ContextCandidate], ContextRetrievalReport]:
        started = perf_counter()
        if not policy.retrieval.enabled:
            return [], ContextRetrievalReport(status="skipped", node_id=query.node_id)
        candidates: list[ContextCandidate] = []
        source_counts: dict[str, int] = {}
        try:
            for source_id in policy.retrieval.source_ids:
                source = self.sources.get(source_id)
                if source is None:
                    continue
                items = [
                    item
                    for item in source.retrieve(query=query, runtime_context=runtime_context)
                    if item.score >= policy.retrieval.min_score
                ]
                source_counts[source_id] = len(items)
                candidates.extend(items)
                if len(candidates) >= policy.retrieval.max_candidates:
                    candidates = candidates[: policy.retrieval.max_candidates]
                    break
            return (
                candidates,
                ContextRetrievalReport(
                    status="completed",
                    node_id=query.node_id,
                    source_counts=source_counts,
                    candidate_count=len(candidates),
                    token_estimate=sum(item.token_estimate for item in candidates),
                    duration_ms=int((perf_counter() - started) * 1000),
                ),
            )
        except Exception as exc:
            return (
                [],
                ContextRetrievalReport(
                    status="failed",
                    node_id=query.node_id,
                    source_counts=source_counts,
                    error=f"{type(exc).__name__}: {exc}",
                    duration_ms=int((perf_counter() - started) * 1000),
                ),
            )

    def _query_for_state(self, *, state: Any, node_id: str, impl: str, messages: list[Any]) -> ContextQuery:
        user_input = str(getattr(getattr(state, "conversation", None), "current_user_input", "") or "")
        chunks = [user_input]
        for message in messages[-4:]:
            content = getattr(message, "content", "")
            if content:
                chunks.append(str(content))
        text = "\n".join(chunk for chunk in chunks if chunk.strip())
        return ContextQuery(node_id=node_id, impl=impl, user_input=user_input or None, text=text)


def default_context_runtime(config: ContextContractConfig | None = None) -> ContextSystemRuntime:
    return ContextSystemRuntime(config=config or ContextContractConfig())


def _factory_query_text(*, stage_id: str, values: dict[str, Any]) -> str:
    chunks = [stage_id]
    for key in ("user_input", "requirement", "requirement_brief", "refined_requirement", "messages"):
        value = values.get(key)
        if value:
            chunks.append(str(value))
    return "\n".join(chunks)
