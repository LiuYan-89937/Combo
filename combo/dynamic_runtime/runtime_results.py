from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.messages import BaseMessage

from combo.context_system.token_estimation import estimate_messages_tokens
from combo.context_system.history import conversation_projection_history
from combo.dynamic_runtime.conversation_projection import graph_messages_to_conversation
from combo.runtime_kernel.observability.emitter import ObservabilityManager
from combo.runtime_kernel.state import RuntimeState
from combo.runtime_protocol import (
    CapabilitySnapshot,
    ConversationMessage,
    RuntimeErrorEnvelope,
    RuntimeInstance,
    RuntimeModelUsage,
    ToolCallPart,
    ToolCallRecord,
    ToolResultPart,
)
from combo.runtime_protocol.contracts import RuntimeExecutionStatus
from combo.runtime_protocol.messages import close_incomplete_tool_call_messages


@dataclass(frozen=True, slots=True)
class RuntimeMessageProjection:
    context_messages: list[BaseMessage]
    transcript_graph_messages: list[BaseMessage]
    conversation_messages: list[ConversationMessage]
    tool_calls: tuple[ToolCallRecord, ...]


def interrupt_payloads(*, raw: Any, checkpoint: Any) -> list[dict[str, Any]]:
    values: list[Any] = []
    if isinstance(raw, dict):
        values.extend(list(raw.get("__interrupt__") or []))
    for task in list(getattr(checkpoint, "tasks", ()) or ()):
        values.extend(list(getattr(task, "interrupts", ()) or ()))
    payloads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        value = getattr(item, "value", item)
        payload = dict(value) if isinstance(value, dict) else {"value": value}
        interrupt_id = str(getattr(item, "id", "") or "").strip()
        if interrupt_id:
            payload["interrupt_id"] = interrupt_id
        marker = repr(sorted(payload.items(), key=lambda pair: str(pair[0])))
        if marker not in seen:
            seen.add(marker)
            payloads.append(payload)
    return payloads


def close_terminal_tool_calls(
    graph_messages: list[BaseMessage],
    *,
    status: str,
) -> list[BaseMessage]:
    if status not in {"completed", "failed", "cancelled"}:
        raise ValueError(f"tool-call closure requires a terminal status: {status}")
    return close_incomplete_tool_call_messages(
        graph_messages,
        status="cancelled" if status == "cancelled" else "failed",
        error_code="runtime_cancelled" if status == "cancelled" else "runtime_terminal_before_tool_result",
    )


def project_runtime_messages(
    *,
    instance: RuntimeInstance,
    snapshot: CapabilitySnapshot,
    state: RuntimeState,
    status: RuntimeExecutionStatus,
    graph_messages: list[BaseMessage],
    current_user_message_id: str,
    graph_store: Any,
) -> RuntimeMessageProjection:
    terminal = status in {"completed", "failed", "cancelled"}
    context_messages = close_terminal_tool_calls(graph_messages, status=status) if terminal else graph_messages
    transcript_graph_messages = conversation_projection_history(
        store=graph_store,
        state=state,
        messages=context_messages,
    )
    if terminal:
        transcript_graph_messages = close_terminal_tool_calls(transcript_graph_messages, status=status)
    projected_for_records = graph_messages_to_conversation(
        graph_messages=transcript_graph_messages,
        current_user_message_id=current_user_message_id,
        session_id=instance.request.session_id,
        turn_id=instance.request.turn_id,
        runtime_instance_id=instance.runtime_instance_id,
        request_id=instance.request.request_id,
        task_revision=instance.request.task_revision,
        capability_snapshot=snapshot,
        message_created_at=model_message_created_at(state.observability.events),
    )
    conversation_messages = (
        []
        if instance.request.runtime_role == "temporary" or status in {"waiting_approval", "waiting_external"}
        else projected_for_records
    )
    return RuntimeMessageProjection(
        context_messages=context_messages,
        transcript_graph_messages=transcript_graph_messages,
        conversation_messages=conversation_messages,
        tool_calls=project_tool_call_records(
            projected_for_records,
            instance=instance,
            waiting_status=status,
            observations=state.observability.events,
        ),
    )


def project_tool_call_records(
    messages: list[ConversationMessage],
    *,
    instance: RuntimeInstance,
    waiting_status: RuntimeExecutionStatus,
    observations: list[dict[str, Any]],
) -> tuple[ToolCallRecord, ...]:
    if instance.attempt_id is None:
        raise RuntimeError("claimed runtime instance has no attempt identity")
    records: dict[str, dict[str, Any]] = {}
    event_times = _tool_event_times(observations)
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                initial_status = (
                    "waiting_approval"
                    if waiting_status == "waiting_approval"
                    else "running"
                    if waiting_status == "waiting_external"
                    else "proposed"
                )
                observed = event_times.get(part.tool_call_id, {})
                records[part.tool_call_id] = {
                    "tool_call_id": part.tool_call_id,
                    "runtime_instance_id": instance.runtime_instance_id,
                    "request_id": instance.request.request_id,
                    "turn_id": instance.request.turn_id,
                    "attempt_id": instance.attempt_id,
                    "capability_id": part.capability_id,
                    "capability_revision": part.capability_revision,
                    "model_alias": part.model_alias,
                    "display_alias": observed.get("display_alias") or part.model_alias,
                    "arguments": dict(part.arguments),
                    "status": initial_status,
                    "created_at": observed.get("requested_at") or message.created_at,
                    "updated_at": observed.get("started_at") or observed.get("requested_at") or message.created_at,
                    "started_at": observed.get("started_at"),
                    "completed_at": None,
                }
            elif isinstance(part, ToolResultPart):
                record = records.get(part.tool_call_id)
                if record is None:
                    raise RuntimeError(f"tool result has no projected tool call: {part.tool_call_id}")
                record["status"] = part.status
                observed = event_times.get(part.tool_call_id, {})
                started_at = observed.get("started_at") or part.started_at
                completed_at = observed.get("completed_at") or part.completed_at or message.created_at
                record["started_at"] = started_at
                record["completed_at"] = completed_at
                record["updated_at"] = completed_at
                if part.status == "completed":
                    record["result"] = dict(part.output or {})
                else:
                    if part.output:
                        record["result"] = dict(part.output)
                    record["error_code"] = part.error_code
    return tuple(ToolCallRecord.model_validate(record) for record in records.values())


def _tool_event_times(observations: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    event_times: dict[str, dict[str, str]] = {}
    for observation in observations:
        event_type = str(observation.get("event_type") or "")
        if event_type not in {
            "tool_proposed",
            "tool_started",
            "tool_completed",
            "tool_failed",
            "tool_contract_invalid",
        }:
            continue
        payload = observation.get("payload")
        if not isinstance(payload, dict):
            continue
        tool_call_id = str(payload.get("tool_call_id") or "").strip()
        created_at = str(observation.get("created_at") or "").strip()
        if not tool_call_id or not created_at:
            continue
        times = event_times.setdefault(tool_call_id, {})
        observed_tool_id = str(payload.get("tool_id") or payload.get("tool_name") or "").strip()
        if observed_tool_id:
            times["display_alias"] = observed_tool_id
        if event_type == "tool_proposed":
            times.setdefault("requested_at", created_at)
        elif event_type == "tool_started":
            times.setdefault("started_at", created_at)
        else:
            times["completed_at"] = created_at
    return event_times


def model_message_created_at(observations: list[dict[str, Any]]) -> dict[str, str]:
    timestamps: dict[str, str] = {}
    for observation in observations:
        if str(observation.get("event_type") or "") != "model_call_started":
            continue
        payload = observation.get("payload")
        if not isinstance(payload, dict):
            continue
        stream_id = str(payload.get("stream_id") or "").strip()
        created_at = str(observation.get("created_at") or "").strip()
        if stream_id and created_at:
            timestamps.setdefault(stream_id, created_at)
    return timestamps


def drain_runtime_observations(manager: ObservabilityManager, *, state: RuntimeState) -> list[dict[str, Any]]:
    events = manager.drain_durable_events(
        trace_id=state.observability.trace_id,
        run_id=state.run.run_id,
    )
    return [event.model_dump(mode="json") for event in events]


def project_model_usage_records(
    instance: RuntimeInstance,
    observations: list[dict[str, Any]],
) -> tuple[RuntimeModelUsage, ...]:
    if instance.attempt_id is None:
        raise RuntimeError("runtime model usage requires a claimed attempt identity")
    request = instance.request
    frozen_model = request.policy_snapshot.model
    if frozen_model.operation == "main_turn":
        model_operation: Literal["main_turn", "temporary_turn"] = "main_turn"
    elif frozen_model.operation == "temporary_turn":
        model_operation = "temporary_turn"
    else:
        raise RuntimeError("runtime usage requires a turn model operation")
    records: list[RuntimeModelUsage] = []
    for observation in observations:
        if str(observation.get("event_type") or "") != "model_usage_completed":
            continue
        payload = observation.get("payload")
        if not isinstance(payload, dict):
            raise RuntimeError("model usage observation payload must be an object")
        if str(payload.get("version") or "") != "runtime_model_usage_observation.v1":
            raise RuntimeError("model usage observation uses an unsupported schema")
        observed_model = (
            str(payload.get("model_operation") or ""),
            str(payload.get("model_profile_id") or ""),
            int(payload.get("model_profile_revision") or 0),
            str(payload.get("provider") or ""),
            str(payload.get("model_name") or ""),
        )
        frozen_identity = (
            frozen_model.operation,
            frozen_model.profile_id,
            frozen_model.profile_revision,
            frozen_model.provider,
            frozen_model.model_name,
        )
        if observed_model != frozen_identity:
            raise RuntimeError("model usage observation differs from the frozen model selection")
        raw_usage_source = str(payload.get("usage_source") or "provider_usage")
        if raw_usage_source == "provider_usage":
            usage_source: Literal["provider_usage", "provider_usage_with_fallback", "local_estimation"] = "provider_usage"
        elif raw_usage_source == "provider_usage_with_fallback":
            usage_source = "provider_usage_with_fallback"
        elif raw_usage_source == "local_estimation":
            usage_source = "local_estimation"
        else:
            raise RuntimeError("model usage observation has an unsupported usage source")
        records.append(
            RuntimeModelUsage(
                observation_event_id=str(observation.get("event_id") or ""),
                principal_id=request.principal_id,
                request_id=request.request_id,
                runtime_instance_id=instance.runtime_instance_id,
                attempt_id=instance.attempt_id,
                session_id=request.session_id,
                turn_id=request.turn_id,
                workspace_id=request.workspace_id,
                task_revision=request.task_revision,
                runtime_role=request.runtime_role,
                strategy=request.strategy,
                node_id=str(payload.get("node_id") or ""),
                model_operation=model_operation,
                model_profile_id=frozen_model.profile_id,
                model_profile_revision=frozen_model.profile_revision,
                provider=frozen_model.provider,
                model_name=frozen_model.model_name,
                input_tokens=int(payload.get("input_tokens") or 0),
                output_tokens=int(payload.get("output_tokens") or 0),
                total_tokens=int(payload.get("total_tokens") or 0),
                reasoning_tokens=int(payload.get("reasoning_tokens") or 0),
                cache_read_tokens=int(payload.get("cache_read_tokens") or 0),
                cache_write_tokens=int(payload.get("cache_write_tokens") or 0),
                usage_source=usage_source,
                created_at=str(observation.get("created_at") or ""),
            )
        )
    return tuple(records)


def runtime_event_payload(
    instance: RuntimeInstance,
    *,
    state: RuntimeState,
    status: RuntimeExecutionStatus,
    interrupts: list[dict[str, Any]],
    error: RuntimeErrorEnvelope | None,
    graph_messages: list[BaseMessage],
    conversation_messages: list[ConversationMessage],
    tool_calls: tuple[ToolCallRecord, ...],
) -> dict[str, Any]:
    if status in {"waiting_approval", "waiting_external"}:
        source = (
            {
                "task_id": instance.request.task_id,
                "parent_runtime_instance_id": instance.request.parent_runtime_instance_id,
                "runtime_role": instance.request.runtime_role,
            }
            if instance.request.runtime_role == "temporary"
            else {"runtime_role": instance.request.runtime_role}
        )
        return {
            "kind": f"runtime_{status}",
            "status": status,
            "details": {
                "interrupts": _json_safe(interrupts),
                "source": source,
            },
        }
    if status == "completed":
        assistant_message = next(
            (message for message in reversed(conversation_messages) if message.role == "assistant"),
            None,
        )
        final_content = final_graph_message_content(graph_messages)
        result = (
            {
                "summary": final_content,
                "verified": True,
                "tool_evidence": [
                    {
                        "tool": record.model_alias,
                        "status": record.status,
                        "result": record.result,
                    }
                    for record in tool_calls
                ],
            }
            if instance.request.runtime_role == "temporary"
            else final_content
        )
        return {
            "kind": "runtime_completed",
            "status": "completed",
            "result": result,
            "message": (
                {
                    "message_id": assistant_message.message_id,
                    "parts": [part.model_dump(mode="json") for part in assistant_message.parts],
                    "created_at": assistant_message.created_at,
                }
                if assistant_message is not None
                else None
            ),
            "context_window": latest_context_window(state),
        }
    if error is None:
        raise RuntimeError(f"terminal runtime status requires an error envelope: {status}")
    return {"kind": status, "error": error.model_dump(mode="json")}


def latest_context_window(
    state: RuntimeState,
    *,
    graph_messages: list[Any] | None = None,
) -> dict[str, Any] | None:
    persisted = _context_window_from_token_budget(state, graph_messages=graph_messages)
    observed = _latest_observed_context_window(state)
    if persisted is not None:
        return recompute_context_window_ratios(
            {
                **(observed or {}),
                **{
                    key: value
                    for key, value in persisted.items()
                    if value is not None
                },
                "compression_status": _latest_compression_status(state),
            }
        )
    if observed is not None:
        return recompute_context_window_ratios(
            {
                **observed,
                "compression_status": _latest_compression_status(state),
            }
        )
    return None


def _latest_observed_context_window(state: RuntimeState) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    for raw_event in reversed(state.observability.events):
        if not isinstance(raw_event, dict) or raw_event.get("event_type") != "context_window_updated":
            continue
        payload = raw_event.get("payload")
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if key == "event_type" or value is None or key in merged:
                continue
            merged[key] = _json_safe(value)
    return merged or None


def _latest_compression_status(state: RuntimeState) -> str | None:
    statuses = {
        "context_compression_started": "running",
        "context_compression_completed": "completed",
        "context_compression_failed": "failed",
    }
    for raw_event in reversed(state.observability.events):
        if not isinstance(raw_event, dict):
            continue
        event_type = str(raw_event.get("event_type") or "")
        if event_type in statuses:
            return statuses[event_type]
    return None


def _context_window_from_token_budget(
    state: RuntimeState,
    *,
    graph_messages: list[Any] | None = None,
) -> dict[str, Any] | None:
    token_budget = dict(getattr(state.context, "token_budget", {}) or {})
    token_count = token_budget.get("token_count")
    if token_count is None:
        token_count = (
            token_budget.get("effective_context_tokens")
            or token_budget.get("last_provider_context_tokens_after_call")
        )
    token_count_method = (
        token_budget.get("token_count_method")
        or token_budget.get("last_provider_token_count_method")
    )
    source = (
        token_budget.get("source")
        or token_budget.get("effective_context_source")
    )
    baseline_message_tokens = non_negative_int(
        token_budget.get("last_provider_message_tokens_after_call")
    )
    normalized_token_count = non_negative_int(token_count)
    current_message_tokens = (
        estimate_messages_tokens(graph_messages)
        if graph_messages is not None
        else None
    )
    if (
        normalized_token_count is not None
        and baseline_message_tokens is not None
        and current_message_tokens is not None
    ):
        normalized_token_count = max(
            0,
            normalized_token_count + current_message_tokens - baseline_message_tokens,
        )
        token_count_method = f"{token_count_method or 'provider_usage'}_current_context"
        source = "runtime_checkpoint.current_context"
    if normalized_token_count is not None:
        return {
            "token_count": normalized_token_count,
            "context_window_tokens": _json_safe(token_budget.get("context_window_tokens")),
            "compression_threshold_tokens": _json_safe(token_budget.get("compression_threshold_tokens")),
            "token_count_method": _json_safe(token_count_method),
            "source": _json_safe(source),
            "model_role": _json_safe(
                token_budget.get("model_role")
                or token_budget.get("last_provider_model_role")
            ),
            "node_id": _json_safe(
                token_budget.get("node_id")
                or token_budget.get("last_provider_node_id")
            ),
            "current_message_token_estimate": current_message_tokens,
        }
    return None


def recompute_context_window_ratios(window: dict[str, Any]) -> dict[str, Any]:
    """Derive ratios from the final count and active limits.

    Observation events are append-only and may have been produced by a
    previous runtime model.  Their ratios are therefore presentation data, not
    authoritative state.  Recomputing here prevents an old threshold from
    surviving a model switch.
    """
    result = dict(window)
    token_count = non_negative_int(result.get("token_count"))
    context_window_tokens = _positive_int(result.get("context_window_tokens"))
    compression_threshold_tokens = _positive_int(result.get("compression_threshold_tokens"))
    if token_count is not None and context_window_tokens:
        result["window_usage_ratio"] = min(
            float(token_count) / float(context_window_tokens),
            1.0,
        )
    else:
        result.pop("window_usage_ratio", None)
    if token_count is not None and compression_threshold_tokens:
        result["compression_usage_ratio"] = min(
            float(token_count) / float(compression_threshold_tokens),
            1.0,
        )
    else:
        result.pop("compression_usage_ratio", None)
    return result


def final_graph_message_content(messages: list[BaseMessage]) -> Any:
    for message in reversed(messages):
        if getattr(message, "type", "") in {"ai", "assistant"}:
            return _json_safe(getattr(message, "content", ""))
    raise RuntimeError("completed runtime has no assistant result message")


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _positive_int(value: Any) -> int | None:
    parsed = non_negative_int(value)
    return parsed if parsed is not None and parsed > 0 else None
