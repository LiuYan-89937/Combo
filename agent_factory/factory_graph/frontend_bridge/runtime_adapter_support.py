from __future__ import annotations

from typing import Any


def session_payload(record: Any | None) -> dict[str, Any]:
    if record is None:
        return {}
    payload = record.model_dump(mode="json")
    first_user_input = payload.get("first_user_input")
    payload["first_user_input"] = first_user_input
    payload["display_title"] = payload.get("display_title") or display_title(first_user_input)
    mode = payload.get("current_mode")
    payload["snapshot"] = {
        "mode": mode,
        "messages": [],
        "pending_interrupt": None,
        "recent_tool_activities": [],
    }
    return payload


def display_title(value: str | None, *, limit: int = 42) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 1]}…"


def bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def extract_interrupt_payload(chunk: Any) -> Any | None:
    if not isinstance(chunk, dict):
        return None
    interrupts = chunk.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0]
    return getattr(first, "value", first)
