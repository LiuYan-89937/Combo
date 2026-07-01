from __future__ import annotations

from typing import Any


def session_payload(record: Any | None, *, snapshot_mode: str | None = None) -> dict[str, Any]:
    if record is None:
        return {}
    payload = record.model_dump(mode="json")
    first_user_input = payload.get("first_user_input")
    payload["first_user_input"] = first_user_input
    payload["display_title"] = payload.get("display_title") or display_title(first_user_input)
    mode = snapshot_mode or payload.get("current_mode")
    messages = _messages_from_session_turns(_turns_for_mode(payload, mode))
    payload["mode_titles"] = {
        "chat": display_title(_first_turn_input(payload.get("chat_turns"))),
        "create_agent": display_title(_first_turn_input(payload.get("create_agent_turns"))),
        "evolve_agent": display_title(_first_turn_input(payload.get("evolve_agent_turns"))),
    }
    payload["mode_turn_counts"] = {
        "chat": int(payload.get("chat_turn_count") or 0),
        "create_agent": int(payload.get("create_agent_turn_count") or 0),
        "evolve_agent": int(payload.get("evolve_agent_turn_count") or 0),
    }
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


def _messages_from_session_turns(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    messages: list[dict[str, Any]] = []
    for index, turn in enumerate(value, start=1):
        if not isinstance(turn, dict):
            continue
        turn_index = turn.get("index") or index
        user_input = str(turn.get("user_input") or "").strip()
        if user_input:
            messages.append(
                {
                    "role": "user",
                    "content": user_input,
                    "turn_index": turn_index,
                    "created_at": turn.get("created_at"),
                }
            )
        final_answer = str(turn.get("final_answer") or "").strip()
        if final_answer:
            messages.append(
                {
                    "role": "assistant",
                    "content": final_answer,
                    "turn_index": turn_index,
                    "created_at": turn.get("updated_at") or turn.get("created_at"),
                }
            )
    return messages


def _turns_for_mode(payload: dict[str, Any], mode: str | None) -> Any:
    if mode == "chat":
        return payload.get("chat_turns")
    if mode == "create_agent":
        return payload.get("create_agent_turns")
    if mode == "evolve_agent":
        return payload.get("evolve_agent_turns")
    return payload.get("turns")


def _first_turn_input(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for turn in value:
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("user_input") or "").strip()
        if text:
            return text
    return None


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
