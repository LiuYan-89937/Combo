from __future__ import annotations

from typing import Any

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent, event
from agent_factory.package_runtime.request_lifecycle import RuntimeRequestPolicy


RUN_TERMINAL_EVENT_TYPES = {
    "run_completed",
    "run_failed",
}

INTERRUPT_TERMINAL_EVENT_TYPES = {
    "tool_approval_requested",
    "interrupt_requested",
}

REQUEST_TERMINAL_EVENT_TYPES = {
    *RUN_TERMINAL_EVENT_TYPES,
    *INTERRUPT_TERMINAL_EVENT_TYPES,
    "agent_package_sessions_listed",
    "error",
}

TERMINAL_EVENT_TYPES = REQUEST_TERMINAL_EVENT_TYPES


def node_event(
    request_id: str,
    event_type: str,
    *,
    node_id: str,
    payload: dict[str, Any],
    severity: str | None = None,
) -> FactoryFrontendEvent:
    return event(
        event_type,  # type: ignore[arg-type]
        request_id=request_id,
        mode="agent_package",
        graph_id="agent_package_runtime",
        producer_type="agent_runtime_host",
        node_id=node_id,
        node_label="Runtime Container",
        node_kind="system",
        severity=severity,
        payload=payload,
    )


def run_failed_event(request_id: str, payload: dict[str, Any]) -> FactoryFrontendEvent:
    return event(
        "run_failed",
        request_id=request_id,
        mode="agent_package",
        graph_id="agent_package_runtime",
        producer_type="agent_runtime_host",
        severity="error",
        message=str(payload.get("message") or "agent runtime launch failed"),
        payload=payload,
    )


def request_heartbeat_event(
    request_id: str,
    *,
    package_id: str,
    elapsed_seconds: float,
    timeout_seconds: int,
) -> FactoryFrontendEvent:
    return event(
        "node_progress",
        request_id=request_id,
        mode="agent_package",
        graph_id="agent_package_runtime",
        producer_type="agent_runtime_host",
        node_id="runtime_request",
        node_label="Runtime Request",
        node_kind="system",
        message="runtime request is still running",
        payload={
            "package_id": package_id,
            "status": "running",
            "elapsed_seconds": round(elapsed_seconds, 3),
            "timeout_seconds": timeout_seconds,
        },
    )


def request_timeout_payload(
    *,
    package_id: str,
    request_id: str,
    elapsed_seconds: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    return {
        "where": "runtime_request",
        "why": "request_timeout",
        "message": f"Runtime request timed out after {timeout_seconds} seconds.",
        "suggested_action": "Retry the request or split it into smaller steps.",
        "package_id": package_id,
        "request_id": request_id,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "timeout_seconds": timeout_seconds,
    }


def request_cancelled_payload(*, package_id: str, request_id: str, reason: str) -> dict[str, Any]:
    return {
        "where": "runtime_request",
        "why": "request_cancelled",
        "message": "Runtime request was cancelled.",
        "suggested_action": "Send a new message when you are ready to continue.",
        "package_id": package_id,
        "request_id": request_id,
        "reason": reason,
    }


def request_timed_out(started_at: float, now: float, policy: RuntimeRequestPolicy) -> bool:
    return policy.timeout_seconds > 0 and (now - started_at) >= policy.timeout_seconds


def heartbeat_due(last_heartbeat_at: float, now: float, policy: RuntimeRequestPolicy) -> bool:
    return policy.heartbeat_seconds > 0 and (now - last_heartbeat_at) >= policy.heartbeat_seconds


def is_terminal_request_event(item: Any, request_id: str) -> bool:
    return (
        isinstance(item, FactoryFrontendEvent)
        and item.request_id == request_id
        and item.event_type in REQUEST_TERMINAL_EVENT_TYPES
    )


def runtime_stream_status(item: FactoryFrontendEvent) -> str:
    if item.event_type in {"run_failed", "error"}:
        return "failed"
    if item.event_type in INTERRUPT_TERMINAL_EVENT_TYPES:
        return "interrupted"
    return "completed"
