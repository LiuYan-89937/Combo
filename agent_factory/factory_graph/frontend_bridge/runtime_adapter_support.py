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
    messages = _messages_from_turns(payload.get("turns"))
    payload["snapshot"] = {
        "mode": mode,
        "messages": messages,
        "pending_interrupt": None,
        "recent_tool_activities": [],
    }
    return payload


def _messages_from_turns(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    messages: list[dict[str, Any]] = []
    for turn in value[-6:]:
        if not isinstance(turn, dict):
            continue
        if str(turn.get("user_input") or "").strip():
            messages.append(
                {
                    "role": "user",
                    "content": str(turn["user_input"]),
                    "turn_index": turn.get("index"),
                    "created_at": turn.get("created_at"),
                }
            )
        if str(turn.get("final_answer") or "").strip():
            messages.append(
                {
                    "role": "assistant",
                    "content": str(turn["final_answer"]),
                    "turn_index": turn.get("index"),
                    "created_at": turn.get("created_at"),
                }
            )
    return messages


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
    return interrupt_payload(first)


def interrupt_payload(interrupt: Any) -> Any:
    value = getattr(interrupt, "value", interrupt)
    interrupt_id = str(getattr(interrupt, "id", "") or "").strip()
    if not interrupt_id:
        return value
    if isinstance(value, dict):
        return {**value, "interrupt_id": interrupt_id}
    return {"value": value, "interrupt_id": interrupt_id}
