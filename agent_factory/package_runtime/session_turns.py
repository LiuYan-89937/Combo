from __future__ import annotations

from typing import Any

from agent_factory.trace_system import runtime_trace_ref


def session_final_answer(state: Any) -> str | None:
    conversation = getattr(state, "conversation", None)
    if conversation is None:
        return None
    return str(
        getattr(conversation, "final_answer", None)
        or getattr(conversation, "assistant_draft", None)
        or ""
    ).strip() or None


def session_trace_ref(compiled: Any, state: Any) -> dict[str, str] | None:
    trace_id = str(getattr(getattr(state, "observability", None), "trace_id", "") or "").strip()
    run_id = str(getattr(getattr(state, "run", None), "run_id", "") or "").strip()
    services = getattr(compiled, "services", None)
    recorder = getattr(services, "trace_recorder", None) if services is not None else None
    return runtime_trace_ref(recorder=recorder, trace_id=trace_id, run_id=run_id)


def resume_user_input(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("message", "response", "value", "text", "user_input"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    approval = payload.get("approval")
    if isinstance(approval, dict):
        decision = str(approval.get("decision") or approval.get("action") or "").strip()
        return decision or None
    return None
