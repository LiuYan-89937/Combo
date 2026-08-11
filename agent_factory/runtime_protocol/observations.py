from __future__ import annotations

import json
from typing import Any


def looks_like_internal_observation_text(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return False
    return looks_like_internal_observation_payload(payload)


def looks_like_internal_observation_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    keys = {str(key) for key in payload}
    return (
        payload.get("type") == "tool_observation"
        or {"tool_id", "tool_call_id"}.issubset(keys)
        or "output_ref" in keys
        or "output_summary" in keys
    )
