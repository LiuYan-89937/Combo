from __future__ import annotations

from typing import Any
from uuid import uuid4

from langgraph.config import get_stream_writer

from agent_factory.tooling.envelope import tool_envelope


PROGRESS_STATUSES = frozenset({"running", "completed", "blocked"})
DEFAULT_REPLACE_KEY = "current_agent_progress"


def run(arguments: dict[str, Any], _resources: dict[str, Any]) -> dict[str, Any]:
    summary = _required_text(arguments, "summary")
    stage = _required_text(arguments, "stage")
    status = str(arguments.get("status") or "running").strip()
    if status not in PROGRESS_STATUSES:
        raise ValueError(f"status must be one of {sorted(PROGRESS_STATUSES)}")
    replace_key = str(arguments.get("replace_key") or DEFAULT_REPLACE_KEY).strip()
    if not replace_key:
        raise ValueError("replace_key must be a non-empty string")
    progress_id = uuid4().hex
    payload = {
        "progress_id": progress_id,
        "source": "agent",
        "stage": stage,
        "summary": summary,
        "status": status,
        "replace_key": replace_key,
    }
    reported = _emit_progress(payload)
    return tool_envelope(
        {
            "reported": reported,
            "progress_id": progress_id,
            "stage": stage,
            "status": status,
            "replace_key": replace_key,
        }
    )


def _emit_progress(payload: dict[str, Any]) -> bool:
    try:
        writer = get_stream_writer()
        writer({"type": "assistant_progress", "payload": payload})
    except Exception:
        return False
    return True


def _required_text(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()
