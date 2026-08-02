from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


MAX_PARALLEL_SUB_AGENTS_ENV = "AGENTFACTORY_MAX_PARALLEL_SUB_AGENTS"
DEFAULT_MAX_PARALLEL_SUB_AGENTS = 5


@dataclass(frozen=True, slots=True)
class ChatInferenceCapacity:
    profile_id: str
    total_slots: int
    busy_slots: int
    deferred_requests: int
    available_slots: int
    source: str
    live: bool
    detail: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "total_slots": self.total_slots,
            "busy_slots": self.busy_slots,
            "deferred_requests": self.deferred_requests,
            "available_slots": self.available_slots,
            "source": self.source,
            "live": self.live,
            "detail": self.detail,
        }


def inspect_configured_inference_capacity() -> ChatInferenceCapacity:
    raw = str(os.getenv(MAX_PARALLEL_SUB_AGENTS_ENV) or "").strip()
    if not raw:
        return ChatInferenceCapacity(
            profile_id="",
            total_slots=DEFAULT_MAX_PARALLEL_SUB_AGENTS,
            busy_slots=0,
            deferred_requests=0,
            available_slots=DEFAULT_MAX_PARALLEL_SUB_AGENTS,
            source="default_sub_agent_limit",
            live=False,
        )
    try:
        total_slots = int(raw)
    except ValueError:
        return _unavailable(f"{MAX_PARALLEL_SUB_AGENTS_ENV} must be a positive integer")
    if total_slots <= 0:
        return _unavailable(f"{MAX_PARALLEL_SUB_AGENTS_ENV} must be a positive integer")
    return ChatInferenceCapacity(
        profile_id="",
        total_slots=total_slots,
        busy_slots=0,
        deferred_requests=0,
        available_slots=total_slots,
        source="configured_limit",
        live=False,
    )


def normalize_max_parallel_sub_agents(
    value: Any,
    *,
    fallback: int = DEFAULT_MAX_PARALLEL_SUB_AGENTS,
) -> int:
    if value is None or str(value).strip() == "":
        return fallback
    if isinstance(value, bool):
        raise ValueError("max_parallel_sub_agents must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_parallel_sub_agents must be a positive integer") from exc
    if normalized <= 0:
        raise ValueError("max_parallel_sub_agents must be a positive integer")
    return normalized


def _unavailable(detail: str) -> ChatInferenceCapacity:
    return ChatInferenceCapacity(
        profile_id="",
        total_slots=0,
        busy_slots=0,
        deferred_requests=0,
        available_slots=0,
        source="unavailable",
        live=False,
        detail=detail,
    )
