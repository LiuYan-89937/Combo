from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from agent_factory.runtime_kernel.observability.schema import TraceEvent, TraceSpan, TraceSummary


SECRET_KEY_PARTS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "token",
)


class ObservabilityManager:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self.spans: dict[str, TraceSpan] = {}
        self.summaries: dict[str, TraceSummary] = {}
        self._run_started_at: dict[str, float] = {}

    def emit(self, event: TraceEvent) -> None:
        event.payload = _redact(event.payload)
        if event.message:
            event.message = _redact_text(event.message)
        self.events.append(event)
        summary = self._summary_for(event)
        if summary.finished_at is None and event.event_type != "run_completed":
            summary.status = "running"
        if event.event_type == "run_started":
            self._run_started_at[event.run_id] = perf_counter()
            summary.agent_id = str(event.payload.get("agent_id") or summary.agent_id)
            summary.pattern_id = str(event.payload.get("pattern_id") or summary.pattern_id)
        elif event.event_type == "node_completed":
            summary.node_count += 1
            duration = int(event.payload.get("duration_ms") or 0)
            if duration > summary.max_node_latency_ms:
                summary.max_node_latency_ms = duration
        elif event.event_type == "subgraph_exited":
            summary.subgraph_count += 1
        elif event.event_type == "tool_started":
            summary.tool_call_count += 1
        elif event.event_type == "interrupt_triggered":
            summary.interrupt_count += 1
        elif event.event_type == "resume_completed":
            summary.resume_count += 1
        elif event.event_type == "run_completed":
            summary.finished_at = datetime.now(timezone.utc).isoformat()
            summary.status = str(event.payload.get("finish_status") or event.message or "completed")
            started = self._run_started_at.get(event.run_id)
            if started is not None:
                summary.total_latency_ms = int((perf_counter() - started) * 1000)
            summary.turn_count = int(event.payload.get("turn_count") or summary.turn_count)

    def emit_dict(self, data: dict[str, Any]) -> None:
        self.emit(TraceEvent.model_validate(data))

    def list_events(self) -> list[TraceEvent]:
        return list(self.events)

    def start_span(self, *, trace_id: str, run_id: str, span_type: str, name: str, parent_span_id: str | None = None, metadata: dict[str, Any] | None = None) -> TraceSpan:
        span = TraceSpan(
            parent_span_id=parent_span_id,
            span_type=span_type,
            name=name,
            metadata=_redact(metadata or {}),
        )
        self.spans[span.span_id] = span
        self.emit(
            TraceEvent(
                trace_id=trace_id,
                run_id=run_id,
                event_type=f"{span_type}_started",
                message=name,
                payload={"span_id": span.span_id, "parent_span_id": parent_span_id},
            )
        )
        return span

    def finish_span(self, span_id: str, *, trace_id: str, run_id: str, status: str = "completed", metadata: dict[str, Any] | None = None) -> None:
        if span_id not in self.spans:
            return
        span = self.spans[span_id]
        span.finished_at = datetime.now(timezone.utc).isoformat()
        span.status = status  # type: ignore[assignment]
        if metadata:
            span.metadata.update(_redact(metadata))
        self.emit(
            TraceEvent(
                trace_id=trace_id,
                run_id=run_id,
                event_type=f"{span.span_type}_finished",
                message=span.name,
                payload={"span_id": span_id, "status": status, **(metadata or {})},
            )
        )

    def summary_for(self, run_id: str) -> TraceSummary | None:
        return self.summaries.get(run_id)

    def _summary_for(self, event: TraceEvent) -> TraceSummary:
        if event.run_id not in self.summaries:
            self.summaries[event.run_id] = TraceSummary(
                trace_id=event.trace_id,
                run_id=event.run_id,
                agent_id=str(event.payload.get("agent_id") or "unknown-agent"),
                pattern_id=str(event.payload.get("pattern_id") or "unknown-pattern"),
            )
        return self.summaries[event.run_id]


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SECRET_KEY_PARTS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(item)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(value: str) -> str:
    text = value
    for marker in SECRET_KEY_PARTS:
        if marker in text.lower():
            return "[REDACTED]"
    return text
