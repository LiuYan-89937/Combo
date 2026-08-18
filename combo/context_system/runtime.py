from __future__ import annotations

from time import perf_counter
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from combo.context_system.assembly import assemble_context_frame
from combo.context_system.compression import maybe_compress_messages
from combo.context_system.events import emit_context_event
from combo.context_system.schema import (
    ContextCandidate,
    ContextContractConfig,
    ContextInjectionReport,
    ContextPolicy,
    ContextQuery,
    ContextRetrievalReport,
    LLMContextFrame,
)
from combo.context_system.sources import ContextSource, ContextSourceRuntime, default_context_sources
from combo.context_system.token_counter import (
    ModelContextLimits,
    TokenCountResult,
    count_messages_tokens,
    context_window_payload,
    context_limits_with_overrides,
    model_context_limits as resolve_model_context_limits,
)
from combo.context_system.token_estimation import estimate_messages_tokens, estimate_text_tokens


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
        self.sources = dict(sources or {})

    def prepare_before_model_call(
        self,
        *,
        state: Any,
        node_id: str,
        impl: str,
        messages: list[Any],
        services: Any = None,
        resources: Mapping[str, Any] | None = None,
        enable_dynamic_evidence: bool = True,
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
        policy = _effective_context_policy(self.config.default_policy, resources)
        model_role = _runtime_model_operation(services, state=state)
        active_limits = self.model_context_limits(
            services=services,
            state=state,
            model_role=model_role,
        )
        compression_policy = policy.compression.model_copy(
            update={"trigger_token_threshold": active_limits.compression_trigger_tokens}
        )
        working_messages = list(messages)
        working_state = state
        measured_count = count_messages_tokens(working_messages, services=services)
        effective_count = _effective_compression_count(
            state=working_state,
            measured_count=measured_count,
            model_role=model_role,
        )
        compression_result_counter = _compression_result_counter(services=services)
        compression_messages, compression_report = maybe_compress_messages(
            messages=working_messages,
            policy=compression_policy,
            node_id=node_id,
            token_counter=compression_result_counter,
            trigger_count=effective_count,
            on_start=lambda report: emit_context_event(
                services=services,
                state=working_state,
                event_type="context_compression_started",
                node_id=node_id,
                payload=report.model_dump(mode="json"),
            ),
        )
        compression_event_type = {
            "completed": "context_compression_completed",
            "failed": "context_compression_failed",
            "skipped": "context_compression_skipped",
        }.get(compression_report.status, "context_compression_skipped")
        emit_context_event(
            services=services,
            state=working_state,
            event_type=compression_event_type,
            node_id=node_id,
            payload=compression_report.model_dump(mode="json"),
        )
        if compression_report.status == "completed":
            working_state = _state_with_compressed_token_budget(
                state=working_state,
                compression_report=compression_report,
                messages=compression_messages,
            )
            emit_context_event(
                services=services,
                state=working_state,
                event_type="context_window_updated",
                node_id=node_id,
                payload=context_window_payload(
                    node_id=node_id,
                    token_count=compression_report.token_estimate_after,
                    token_count_method=(
                        compression_report.token_count_method or "compression_estimate"
                    ),
                    compression_threshold_tokens=active_limits.compression_trigger_tokens,
                    context_window_tokens=active_limits.context_window_tokens,
                    model_role=model_role,
                    source="context_system.compression",
                ),
            )
        if compression_report.status == "failed":
            raise RuntimeError(compression_report.error or "context compression failed")
        messages_changed = compression_messages != working_messages
        working_messages = compression_messages
        if not enable_dynamic_evidence:
            retrieval_report = ContextRetrievalReport(status="skipped", node_id=node_id)
            injection_report = ContextInjectionReport(status="skipped", node_id=node_id)
            skip_payload = {"reason": "dynamic_evidence_disabled_for_node"}
            emit_context_event(
                services=services,
                state=working_state,
                event_type="context_retrieval_completed",
                node_id=node_id,
                payload={**retrieval_report.model_dump(mode="json"), **skip_payload},
            )
            emit_context_event(
                services=services,
                state=working_state,
                event_type="context_assembly_completed",
                node_id=node_id,
                payload={**injection_report.model_dump(mode="json"), **skip_payload},
            )
            emit_context_event(
                services=services,
                state=working_state,
                event_type="context_injection_completed",
                node_id=node_id,
                payload={**injection_report.model_dump(mode="json"), **skip_payload},
            )
            return ContextPreparationResult(
                state=working_state,
                messages=working_messages,
                messages_changed=messages_changed,
                retrieval_report=retrieval_report,
                injection_report=injection_report,
            )
        reused_frame = _reusable_turn_evidence_frame(state=working_state, node_id=node_id)
        if reused_frame is not None:
            retrieval_report = ContextRetrievalReport(status="skipped", node_id=node_id)
            retrieval_report.selected_count = len(reused_frame.items)
            retrieval_report.token_estimate = reused_frame.token_estimate
            injection_report = ContextInjectionReport(
                status="completed" if reused_frame.text else "skipped",
                node_id=node_id,
                item_count=len(reused_frame.items),
                token_estimate=reused_frame.token_estimate,
            )
            updated = _state_with_turn_evidence(
                state=working_state,
                node_id=node_id,
                frame=reused_frame,
            )
            emit_context_event(
                services=services,
                state=updated,
                event_type="context_retrieval_completed",
                node_id=node_id,
                payload={**retrieval_report.model_dump(mode="json"), "reuse": True},
            )
            emit_context_event(
                services=services,
                state=updated,
                event_type="context_assembly_completed",
                node_id=node_id,
                payload={**injection_report.model_dump(mode="json"), "reuse": True},
            )
            emit_context_event(
                services=services,
                state=updated,
                event_type="context_injection_completed",
                node_id=node_id,
                payload={**injection_report.model_dump(mode="json"), "reuse": True},
            )
            return ContextPreparationResult(
                state=updated,
                messages=working_messages,
                frame=reused_frame,
                messages_changed=messages_changed,
                retrieval_report=retrieval_report,
                injection_report=injection_report,
            )
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
            policy=policy.assembly_policy(),
        )
        retrieval_report.selected_count = len(frame.items)
        retrieval_report.token_estimate = frame.token_estimate
        injection_report = ContextInjectionReport(
            status="completed",
            node_id=node_id,
            item_count=len(frame.items),
            token_estimate=frame.token_estimate,
        )
        updated = _state_with_turn_evidence(state=working_state, node_id=node_id, frame=frame)
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

    def _retrieve(
        self,
        *,
        query: ContextQuery,
        policy: ContextPolicy,
        runtime_context: ContextSourceRuntime,
    ) -> tuple[list[ContextCandidate], ContextRetrievalReport]:
        started = perf_counter()
        memory_policy = policy.cross_session_memory
        if not memory_policy.enabled or not memory_policy.injection_enabled:
            return [], ContextRetrievalReport(status="skipped", node_id=query.node_id)
        candidates: list[ContextCandidate] = []
        source_counts: dict[str, int] = {}
        try:
            for source_id in ("cross_session_memory",):
                source = self.sources.get(source_id)
                if source is None:
                    continue
                items = [
                    item
                    for item in source.retrieve(query=query, runtime_context=runtime_context)
                    if item.score >= memory_policy.min_score
                ]
                source_counts[source_id] = len(items)
                candidates.extend(items)
                if len(candidates) >= memory_policy.max_candidates:
                    candidates = candidates[: memory_policy.max_candidates]
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

    def model_context_limits(
        self,
        *,
        services: Any = None,
        state: Any = None,
        model_role: str = "main",
    ) -> ModelContextLimits:
        compression = self.config.default_policy.compression
        return context_limits_with_overrides(
            resolve_model_context_limits(
                services=services,
                state=state,
                model_role=model_role,
            ),
            context_window_tokens=self.config.context_window_tokens,
            compression_trigger_tokens=compression.trigger_token_threshold,
        )


def default_context_runtime(
    *,
    memory_store: Any,
    config: ContextContractConfig | None = None,
) -> ContextSystemRuntime:
    return ContextSystemRuntime(
        config=config or ContextContractConfig(),
        sources=default_context_sources(memory_store),
    )


def _runtime_model_operation(services: Any, *, state: Any) -> str:
    service = getattr(services, "model_operation_service", None)
    resolver = getattr(service, "operation_for_state", None)
    if callable(resolver):
        return str(resolver(state))
    return "main_turn" if bool(getattr(service, "authoritative_runtime_model", False)) else "main"


def _reusable_turn_evidence_frame(*, state: Any, node_id: str) -> LLMContextFrame | None:
    model_context = getattr(getattr(state, "context", None), "model_context", {}) or {}
    evidence = model_context.get("runtime_turn_evidence") if isinstance(model_context, dict) else None
    if not isinstance(evidence, dict):
        return None
    if evidence.get("run_id") != getattr(getattr(state, "run", None), "run_id", None):
        return None
    if evidence.get("current_user_input") != getattr(getattr(state, "conversation", None), "current_user_input", None):
        return None
    frame = evidence.get("frame")
    if not isinstance(frame, dict):
        return None
    return LLMContextFrame.model_validate(frame)


def _state_with_turn_evidence(*, state: Any, node_id: str, frame: LLMContextFrame) -> Any:
    updated = state.model_copy(deep=True)
    frame_payload = frame.model_dump(mode="json")
    model_context = dict(updated.context.model_context)
    evidence = dict(model_context.get("runtime_turn_evidence") or {})
    evidence = {
        "version": "runtime_turn_evidence.v0",
        "run_id": updated.run.run_id,
        "current_user_input": updated.conversation.current_user_input,
        "source_node_id": str(evidence.get("source_node_id") or node_id),
        "frame": frame_payload,
    }
    updated.context.model_context = {
        **model_context,
        "llm_context_frame": frame_payload,
        node_id: frame_payload,
        "runtime_turn_evidence": evidence,
    }
    return updated


def _effective_context_policy(
    default: ContextPolicy,
    resources: Mapping[str, Any] | None,
) -> ContextPolicy:
    identity = (resources or {}).get("runtime_identity")
    compression = default.compression.model_copy(
        update={
            "detail": str(
                getattr(
                    identity,
                    "context_compression_detail",
                    default.compression.detail,
                )
            ),
            "keep_recent_messages": int(
                getattr(
                    identity,
                    "context_compression_keep_recent_messages",
                    default.compression.keep_recent_messages,
                )
            )
        }
    )
    snapshot = getattr(identity, "memory_policy", None)
    if not isinstance(snapshot, dict):
        return default.model_copy(update={"compression": compression})
    memory = default.cross_session_memory.model_copy(
        update={
            "max_items": int(snapshot["max_items"]),
            "max_tokens": int(snapshot["max_tokens"]),
        }
    )
    return default.model_copy(update={
        "compression": compression,
        "cross_session_memory": memory,
    })

def _effective_compression_count(
    *,
    state: Any,
    measured_count: TokenCountResult,
    model_role: str,
) -> TokenCountResult:
    budget = dict(getattr(getattr(state, "context", None), "token_budget", {}) or {})
    source = str(budget.get("source") or budget.get("effective_context_source") or "")
    observed_role = str(
        budget.get("model_role")
        or budget.get("last_provider_model_role")
        or ""
    )
    observed_count = _positive_token_count(
        budget.get("token_count")
        or budget.get("effective_context_tokens")
        or budget.get("last_provider_context_tokens_after_call")
    )
    baseline_message_count = _positive_token_count(
        budget.get("last_provider_message_tokens_after_call")
    )
    if (
        observed_count is not None
        and baseline_message_count is not None
        and measured_count.token_count is not None
    ):
        observed_count = max(
            0,
            observed_count + measured_count.token_count - baseline_message_count,
        )
    if (
        observed_count is not None
        and (
            source.startswith("model_operation.provider_usage")
            or source == "runtime_checkpoint.current_context"
            or source in {
                "context_system.compression",
                "context_system.manual_compression",
            }
        )
        and (not observed_role or observed_role == model_role)
        and (measured_count.token_count is None or observed_count > measured_count.token_count)
    ):
        return TokenCountResult(
            token_count=observed_count,
            method="provider_usage_calibrated",
            model_role=model_role,
        )
    return measured_count


def _compression_result_counter(*, services: Any):
    def count(items: list[Any]) -> TokenCountResult:
        return count_messages_tokens(items, services=services)

    return count


def _positive_token_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _state_with_compressed_token_budget(
    *,
    state: Any,
    compression_report: ContextCompressionReport,
    messages: list[Any],
) -> Any:
    updated = state.model_copy(deep=True)
    updated.context.token_budget = {
        **dict(getattr(updated.context, "token_budget", {}) or {}),
        "token_count": compression_report.token_estimate_after,
        "token_count_method": compression_report.token_count_method or "compression_estimate",
        "source": "context_system.compression",
        "effective_context_tokens": compression_report.token_estimate_after,
        "effective_context_source": compression_report.token_count_method or "compression_estimate",
        "last_provider_message_tokens_after_call": estimate_messages_tokens(messages),
    }
    return updated
