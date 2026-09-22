from __future__ import annotations

from time import perf_counter
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from combo.context_system.assembly import assemble_context_frame
from combo.context_system.compression import maybe_compress_messages
from combo.context_system.memory_context import (
    context_key, explicit_memory_candidates, memory_query, project_memory_tool_messages,
    read_memory_snapshot, replace_memory_snapshot,
)
from combo.context_system.events import emit_context_event
from combo.context_system.history import archive_context_history
from combo.context_system.schema import (
    ContextCandidate,
    ContextCompressionReport,
    ContextContractConfig,
    ContextInjectionReport,
    ContextPolicy,
    ContextRetrievalReport,
    LLMContextFrame,
    MemoryContextSnapshot,
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
from combo.context_system.token_estimation import estimate_messages_tokens


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
        messages: list[Any],
        services: Any = None,
        resources: Mapping[str, Any] | None = None,
        enable_dynamic_evidence: bool = True,
        protected_input_ids: tuple[str, ...] = (),
    ) -> ContextPreparationResult:
        if not self.config.enabled:
            state = state.model_copy(deep=True)
            replace_memory_snapshot(state, None)
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
        # A runtime may inherit a context count from a previous turn that was
        # executed with a different model.  The count is useful as a baseline,
        # but the window and trigger must always come from the model frozen for
        # this runtime.  Seed the working state before calculating the trigger
        # count so the inherited values cannot make the threshold jump.
        _apply_active_context_limits(
            state=state,
            active_limits=active_limits,
            model_role=model_role,
        )
        compression_policy = policy.compression.model_copy(
            update={"trigger_token_threshold": active_limits.compression_trigger_tokens}
        )
        working_messages = list(messages)
        working_state = state.model_copy(deep=True)
        explicit_candidates = explicit_memory_candidates(working_messages, working_state)
        measured_count = count_messages_tokens(working_messages, services=services)
        effective_count = _effective_compression_count(
            state=working_state,
            measured_count=measured_count,
            model_role=model_role,
        )
        compression_result_counter = _compression_result_counter(services=services)
        (
            summary_model,
            summary_model_max_output_tokens,
            summary_model_metadata,
        ) = _runtime_compression_model(
            services,
            state=working_state,
        )
        compression_messages, compression_report = maybe_compress_messages(
            messages=working_messages,
            policy=compression_policy,
            node_id=node_id,
            protected_message_ids=tuple(filter(None, (
                working_state.conversation.current_user_input_id,
                *protected_input_ids,
            ))),
            token_counter=compression_result_counter,
            trigger_count=effective_count,
            on_start=lambda report: emit_context_event(
                services=services,
                state=working_state,
                event_type="context_compression_started",
                node_id=node_id,
                payload=report.model_dump(mode="json"),
            ),
            summary_model=summary_model,
            summary_model_max_output_tokens=summary_model_max_output_tokens,
            summary_model_metadata=summary_model_metadata,
        )
        if compression_report.status == "completed":
            archive_context_history(
                store=services.graph_store, state=working_state, messages=working_messages,
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
            payload=_compression_event_payload(
                compression_report=compression_report,
                measured_count=measured_count,
                effective_count=effective_count,
                active_limits=active_limits,
                model_role=model_role,
            ),
        )
        if compression_report.status == "completed":
            working_state = _state_with_compressed_token_budget(
                state=working_state,
                compression_report=compression_report,
                messages=compression_messages,
                active_limits=active_limits,
                model_role=model_role,
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
        return self._prepare_memory(
            state=working_state, messages=working_messages, messages_changed=messages_changed,
            explicit_candidates=explicit_candidates, node_id=node_id,
            policy=policy, services=services, resources=resources or {},
            enabled=enable_dynamic_evidence, active_limits=active_limits,
        )

    def _prepare_memory(
        self, *, state: Any, messages: list[Any], messages_changed: bool,
        explicit_candidates: list[ContextCandidate], node_id: str,
        policy: ContextPolicy, services: Any, resources: Mapping[str, Any],
        enabled: bool, active_limits: ModelContextLimits,
    ) -> ContextPreparationResult:
        started = perf_counter()
        memory_policy = policy.cross_session_memory
        query = memory_query(state, node_id=node_id, policy=memory_policy)
        report = ContextRetrievalReport(status="skipped", node_id=node_id, query_components=query.components)
        injection = ContextInjectionReport(status="skipped", node_id=node_id)
        frame = None
        previous = read_memory_snapshot(state)
        replace_memory_snapshot(state, None)
        if not enabled or not memory_policy.enabled or not memory_policy.injection_enabled:
            report.reason = "memory_injection_disabled"
        else:
            runtime_context = ContextSourceRuntime(state=state, resources=resources)
            try:
                identity = runtime_context.memory_identity()
                versions = {key: source.version(runtime_context=runtime_context) for key, source in self.sources.items()}
                versions["automatic_recall"] = str(memory_policy.automatic_recall_enabled)
                reuse = (
                    previous is not None and previous.principal_id == identity.principal_id
                    and previous.source_versions == versions
                    and previous.query.components == query.components
                    and previous.query.limit == query.limit
                    and previous.query.min_relevance == query.min_relevance
                )
                report.reuse = reuse
                report.reason = "same_context_and_source_versions" if reuse else "request_task_source_or_policy_changed"
                if not memory_policy.automatic_recall_enabled:
                    automatic = []
                elif reuse:
                    automatic = [item for item in previous.candidates if item.metadata.get("retrieval_origin") != "explicit"]
                else:
                    automatic = []
                    for source_id, source in self.sources.items():
                        retrieved = source.retrieve(query=query, runtime_context=runtime_context) if query.text else []
                        report.source_counts[source_id] = len(retrieved)
                        automatic.extend(retrieved)
                retained = (
                    [item for item in previous.candidates if item.metadata.get("retrieval_origin") == "explicit"]
                    if previous is not None and previous.principal_id == identity.principal_id else []
                )
                proposed = [*explicit_candidates, *retained, *automatic]
                validated = []
                for source_id, source in self.sources.items():
                    validated.extend(source.validate(
                        [item for item in proposed if item.source_id == source_id], runtime_context=runtime_context,
                    ))
                valid_ids = {item.candidate_id for item in validated}
                unique = {}
                for item in validated:
                    unique.setdefault(item.candidate_id, item)
                candidates = list(unique.values())[:memory_policy.max_candidates]
                after_versions = {key: source.version(runtime_context=runtime_context) for key, source in self.sources.items()}
                report.source_versions = after_versions
                report.status = "completed"
                report.candidate_count = len(candidates)
                assembly = policy.assembly_policy()
                # Full tool memory payloads are replaced by references in the
                # request projection; their contents share this one budget.
                projected = project_memory_tool_messages(messages, selected_ids=set())
                available = max(0, active_limits.compression_trigger_tokens - estimate_messages_tokens(projected))
                assembly = assembly.model_copy(update={"max_tokens_total": min(assembly.max_tokens_total, available)})
                frame = assemble_context_frame(node_id=node_id, query=query, candidates=candidates, policy=assembly)
                frame.decisions.extend(
                    {"candidate_id": item.candidate_id, "reason": "inactive_revision_or_out_of_scope"}
                    for item in proposed if item.candidate_id not in valid_ids
                )
                frame.decisions.extend(
                    {"candidate_id": item.candidate_id, "reason": "candidate_budget"}
                    for item in list(unique.values())[memory_policy.max_candidates:]
                )
                selected_ids = [item.candidate_id for item in frame.items]
                snapshot = MemoryContextSnapshot(
                    context_key=context_key(state), principal_id=identity.principal_id,
                    node_id=node_id, query=query,
                    # If the source changed during retrieval, keep the current
                    # validated frame but retrieve again at the next boundary.
                    source_versions=after_versions if after_versions == versions else {},
                    candidates=candidates, selected_ids=selected_ids,
                    token_estimate=frame.token_estimate, max_tokens=assembly.max_tokens_total,
                )
                replace_memory_snapshot(state, snapshot)
                report.selected_count = len(frame.items)
                report.token_estimate = frame.token_estimate
                injection = ContextInjectionReport(
                    status="completed", node_id=node_id, item_count=len(frame.items),
                    selected_ids=selected_ids, decisions=frame.decisions, token_estimate=frame.token_estimate,
                )
            except Exception as exc:
                report.status = "failed"
                report.error = f"{type(exc).__name__}: {exc}"
                report.reason = "memory_preparation_failed"
                # Do not cache failure as an empty successful retrieval.
                replace_memory_snapshot(state, None)
        report.duration_ms = int((perf_counter() - started) * 1000)
        emit_context_event(services=services, state=state, event_type="context_retrieval_completed",
                           node_id=node_id, payload=report.model_dump(mode="json"))
        for event_type in ("context_assembly_completed", "context_injection_completed"):
            emit_context_event(services=services, state=state, event_type=event_type,
                               node_id=node_id, payload=injection.model_dump(mode="json"))
        return ContextPreparationResult(
            state=state, messages=messages, messages_changed=messages_changed,
            frame=frame, retrieval_report=report, injection_report=injection,
        )

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


def _runtime_compression_model(
    services: Any,
    *,
    state: Any,
) -> tuple[Any | None, int | None, dict[str, Any]]:
    service = getattr(services, "model_operation_service", None)
    resolver = getattr(service, "compression_model_for_state", None)
    if not callable(resolver):
        return None, None, {}
    model, max_output_tokens, metadata = resolver(state)
    return model, max_output_tokens, dict(metadata or {})


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
            "automatic_recall_enabled": bool(snapshot.get("automatic_recall_enabled", True)),
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
                "runtime_checkpoint.inherited_context",
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


def _apply_active_context_limits(
    *,
    state: Any,
    active_limits: ModelContextLimits,
    model_role: str,
) -> None:
    """Make the current runtime model's limits authoritative on its state.

    This deliberately updates the parsed state before the compression call.
    If compression fails, the fixed runner still persists this same state in
    its terminal error patch instead of falling back to an inherited model's
    limits.
    """
    context = getattr(state, "context", None)
    if context is None or not hasattr(context, "token_budget"):
        return
    context.token_budget = {
        **dict(getattr(context, "token_budget", {}) or {}),
        "context_window_tokens": active_limits.context_window_tokens,
        "compression_threshold_tokens": active_limits.compression_trigger_tokens,
        "model_role": model_role,
    }


def _compression_event_payload(
    *,
    compression_report: ContextCompressionReport,
    measured_count: TokenCountResult,
    effective_count: TokenCountResult,
    active_limits: ModelContextLimits,
    model_role: str,
) -> dict[str, Any]:
    return {
        **compression_report.model_dump(mode="json"),
        "measured_token_count": measured_count.token_count,
        "measured_token_count_method": measured_count.method,
        "effective_token_count": effective_count.token_count,
        "effective_token_count_method": effective_count.method,
        "active_context_window_tokens": active_limits.context_window_tokens,
        "active_compression_threshold_tokens": active_limits.compression_trigger_tokens,
        "active_model_role": model_role,
    }


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
    active_limits: ModelContextLimits,
    model_role: str,
) -> Any:
    updated = state.model_copy(deep=True)
    updated.context.compression_applied = True
    updated.context.compression_report = compression_report.model_dump(mode="json")
    updated.context.token_budget = {
        **dict(getattr(updated.context, "token_budget", {}) or {}),
        "token_count": compression_report.token_estimate_after,
        "token_count_method": compression_report.token_count_method or "compression_estimate",
        "source": "context_system.compression",
        "effective_context_tokens": compression_report.token_estimate_after,
        "effective_context_source": compression_report.token_count_method or "compression_estimate",
        "last_provider_message_tokens_after_call": estimate_messages_tokens(messages),
        "context_window_tokens": active_limits.context_window_tokens,
        "compression_threshold_tokens": active_limits.compression_trigger_tokens,
        "model_role": model_role,
    }
    return updated
