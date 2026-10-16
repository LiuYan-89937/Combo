from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RuntimeErrorCategory = Literal[
    "cancelled",
    "timeout",
    "approval_denied",
    "dependency",
    "provider",
    "tool",
    "mcp",
    "validation",
    "conflict",
    "unavailable",
    "internal",
]
RuntimeTerminalStatus = Literal["failed", "cancelled"]
CANCELLATION_ERROR_CODES = frozenset(
    {
        "runtime_cancelled",
        "runtime_steered",
        "user_cancel",
        "user_cancelled",
        "user-cancelled",
    }
)


class RuntimeFailure(BaseModel):
    """Serializable failure shared by graph state, observations and terminal events."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    category: RuntimeErrorCategory
    terminal_status: RuntimeTerminalStatus = "failed"
    retryable: bool = False
    user_message_key: str
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "code",
        "user_message_key",
    )
    @classmethod
    def _required_text(cls, value: str, info: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{info.field_name} must not be empty")
        return text


class RuntimeErrorEnvelope(RuntimeFailure):
    diagnostic_ref: str | None = None
    request_id: str
    runtime_instance_id: str
    operation: str

    @field_validator("request_id", "runtime_instance_id", "operation")
    @classmethod
    def _identity_text(cls, value: str, info: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{info.field_name} must not be empty")
        return text

    @field_validator("diagnostic_ref")
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None


def is_runtime_cancellation(value: Any) -> bool:
    signal = _normalized(value) if isinstance(value, str) else ""
    if signal in CANCELLATION_ERROR_CODES or signal == "model generation was superseded.":
        return True
    return any(_is_cancellation_record(record) for record in _cancellation_records(value))


def _cancellation_records(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, dict):
        return ()
    records: list[dict[str, Any]] = []
    pending = [value]
    seen: set[int] = set()
    while pending:
        record = pending.pop(0)
        identity = id(record)
        if identity in seen:
            continue
        seen.add(identity)
        records.append(record)
        for key in ("error", "result", "output", "observation", "details"):
            nested = record.get(key)
            if isinstance(nested, dict):
                pending.append(nested)
    return tuple(records)


def _is_cancellation_record(value: dict[str, Any]) -> bool:
    code = _normalized(value.get("code") or value.get("error_code"))
    signal = _normalized(
        value.get("error") or value.get("cancel_reason") or value.get("stop_reason")
    )
    category = _normalized(value.get("category"))
    terminal_status = _normalized(value.get("terminal_status"))
    status = _normalized(value.get("status") or value.get("execution_status"))
    exception_type = _normalized(value.get("exception_type"))
    message = _normalized(value.get("message") or value.get("reason"))
    return (
        code in CANCELLATION_ERROR_CODES
        or signal in CANCELLATION_ERROR_CODES
        or category == "cancelled"
        or terminal_status == "cancelled"
        or status in {"cancelled", "steered", "superseded"}
        or exception_type == "runtimemodelgenerationinterrupted"
        or message == "model generation was superseded."
    )


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()
