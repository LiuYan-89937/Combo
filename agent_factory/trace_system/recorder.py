from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import uuid4

from agent_factory.trace_system.schema import TraceFactRecord, TraceReferenceRecord
from agent_factory.trace_system.store import JSONLTraceStore


class TraceRecorder:
    """Append-only trace writer used by RuntimeKernel and SystemPackage runtimes."""

    def __init__(
        self,
        *,
        store: JSONLTraceStore,
        package_id: str | None = None,
        producer_type: str = "agent_runtime",
        max_inline_payload_chars: int = 12000,
    ) -> None:
        self.store = store
        self.package_id = package_id
        self.producer_type = producer_type
        self.max_inline_payload_chars = max_inline_payload_chars
        self._active_spans_by_run: dict[str, list[str]] = defaultdict(list)
        self.last_error: str | None = None

    def ensure_trace(
        self,
        *,
        trace_id: str,
        run_id: str,
        agent_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self._safe(
            self.store.ensure_trace,
            trace_id=trace_id,
            run_id=run_id,
            agent_id=agent_id,
            session_id=session_id,
            package_id=self.package_id,
            producer_type=self.producer_type,
        )

    def record_event(
        self,
        *,
        trace_id: str,
        run_id: str,
        event_type: str,
        node_id: str | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> None:
        self.ensure_trace(trace_id=trace_id, run_id=run_id)
        self._safe(
            self.store.append_fact,
            TraceFactRecord(
                trace_id=trace_id,
                run_id=run_id,
                record_type="event",
                event_type=event_type,
                span_id=self.current_span_id(run_id),
                node_id=node_id,
                message=self._clip_text(message),
                payload=self._clip_payload(payload or {}),
                status=status,
            ),
        )

    def start_span(
        self,
        *,
        trace_id: str,
        run_id: str,
        span_kind: str,
        name: str,
        node_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        self.ensure_trace(trace_id=trace_id, run_id=run_id)
        span_id = uuid4().hex
        parent_span_id = self.current_span_id(run_id)
        self._active_spans_by_run[run_id].append(span_id)
        self._safe(
            self.store.append_fact,
            TraceFactRecord(
                trace_id=trace_id,
                run_id=run_id,
                record_type="span_started",
                event_type=f"{span_kind}.started",
                span_id=span_id,
                parent_span_id=parent_span_id,
                span_kind=span_kind,
                node_id=node_id,
                message=name,
                payload=self._clip_payload(payload or {}),
                status="started",
            ),
        )
        return span_id

    def finish_span(
        self,
        *,
        trace_id: str,
        run_id: str,
        span_id: str,
        span_kind: str,
        name: str,
        status: str,
        node_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        stack = self._active_spans_by_run.get(run_id)
        parent_span_id = None
        if stack:
            if span_id in stack:
                index = stack.index(span_id)
                parent_span_id = stack[index - 1] if index > 0 else None
                del stack[index:]
            else:
                parent_span_id = stack[-1]
        self._safe(
            self.store.append_fact,
            TraceFactRecord(
                trace_id=trace_id,
                run_id=run_id,
                record_type="span_finished",
                event_type=f"{span_kind}.finished",
                span_id=span_id,
                parent_span_id=parent_span_id,
                span_kind=span_kind,
                node_id=node_id,
                message=name,
                payload=self._clip_payload(payload or {}),
                status=status,
            ),
        )

    def record_reference(
        self,
        *,
        trace_id: str,
        run_id: str,
        reference_type: str,
        uri: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._safe(
            self.store.append_reference,
            TraceReferenceRecord(
                trace_id=trace_id,
                run_id=run_id,
                span_id=self.current_span_id(run_id),
                reference_type=reference_type,
                uri=uri,
                metadata=self._clip_payload(metadata or {}),
            ),
        )

    def finish_trace(self, *, trace_id: str, status: str) -> None:
        self._safe(self.store.finish_trace, trace_id=trace_id, status=status)

    def manifest_for(self, trace_id: str) -> dict[str, Any] | None:
        manifest = self.store.manifest_for(trace_id)
        return manifest.model_dump(mode="json") if manifest is not None else None

    def current_span_id(self, run_id: str) -> str | None:
        stack = self._active_spans_by_run.get(run_id)
        return stack[-1] if stack else None

    def _clip_payload(self, value: dict[str, Any]) -> dict[str, Any]:
        text = str(value)
        if len(text) <= self.max_inline_payload_chars:
            return value
        return {
            "truncated": True,
            "preview": text[: self.max_inline_payload_chars],
            "original_chars": len(text),
        }

    def _clip_text(self, value: str | None) -> str | None:
        if value is None or len(value) <= self.max_inline_payload_chars:
            return value
        return value[: self.max_inline_payload_chars]

    def _safe(self, fn, *args, **kwargs) -> None:
        try:
            fn(*args, **kwargs)
            self.last_error = None
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
