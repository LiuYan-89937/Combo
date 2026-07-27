from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any


COLLABORATION_MAX_PARALLEL_WORKERS_ENV = "AGENTFACTORY_COLLABORATION_MAX_PARALLEL_WORKERS"


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
    raw = str(os.getenv(COLLABORATION_MAX_PARALLEL_WORKERS_ENV) or "").strip()
    if not raw:
        return _unavailable(f"{COLLABORATION_MAX_PARALLEL_WORKERS_ENV} is not configured")
    try:
        total_slots = int(raw)
    except ValueError:
        return _unavailable(f"{COLLABORATION_MAX_PARALLEL_WORKERS_ENV} must be a positive integer")
    if total_slots <= 0:
        return _unavailable(f"{COLLABORATION_MAX_PARALLEL_WORKERS_ENV} must be a positive integer")
    return ChatInferenceCapacity(
        profile_id="",
        total_slots=total_slots,
        busy_slots=0,
        deferred_requests=0,
        available_slots=total_slots,
        source="configured_limit",
        live=False,
    )


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
