from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


CONTROL_COMMAND_KINDS = (
    "cancel_command_request",
    "cancel_runtime_request",
    "steer_runtime_request",
)


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
