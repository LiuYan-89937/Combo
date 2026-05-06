from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from agent_factory.runtime_kernel.observability.schema import TraceEvent, TraceSpan, TraceSummary


class ObservabilityManager:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self.spans: dict[str, TraceSpan] = {}
        self.summaries: dict[str, TraceSummary] = {}
        self._run_started_at: dict[str, float] = {}

    def emit(self, event: TraceEvent) -> None:
        self.events.append(event)
        summary = self._summary_for(event)
        summary.status = "running"
        if event.event_type == "run_started":
            self._run_started_at[event.run_id] = perf_counter()
        elif event.event_type == "node_completed":
            summary.node_count += 1
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
            metadata=metadata or {},
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
            span.metadata.update(metadata)
        self.emit(
            TraceEvent(
                trace_id=trace_id,
                run_id=run_id,
                event_type=f"{span.span_type}_finished",
                message=span.name,
                payload={"span_id": span_id, "status": status},
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
