from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Protocol

from combo.dynamic_runtime.repositories import OutboxStore
from combo.runtime_protocol import OutboxRecord


class OutboxEventSink(Protocol):
    def publish(self, record: OutboxRecord) -> Awaitable[None]:
        ...


@dataclass(frozen=True, slots=True)
class OutboxDeliveryPolicy:
    max_attempts: int
    retry_delay_seconds: float

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("outbox max_attempts must be positive")
        if self.retry_delay_seconds <= 0:
            raise ValueError("outbox retry_delay_seconds must be positive")


class OutboxPublisher:
    def __init__(
        self,
        *,
        store: OutboxStore,
        sink: OutboxEventSink,
        policy: OutboxDeliveryPolicy,
    ) -> None:
        self._store = store
        self._sink = sink
        self._policy = policy

    async def publish_one(self) -> bool:
        record = self._store.claim_next()
        if record is None:
            return False
        try:
            await self._sink.publish(record)
        except Exception as exc:
            self._record_failure(record, exc)
            return True
        now = _utc_now()
        published = record.model_copy(
            update={
                "status": "published",
                "published_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "error_code": None,
            }
        )
        self._store.replace(published, expected_status="publishing")
        return True

    def recover_interrupted_publications(self) -> int:
        now = _utc_now().isoformat()
        return self._store.recover_publishing(
            error_code="outbox_publisher_restarted",
            retry_at=now,
        )

    def _record_failure(self, record: OutboxRecord, exc: Exception) -> None:
        now = _utc_now()
        exhausted = record.publish_attempts >= self._policy.max_attempts
        failed = record.model_copy(
            update={
                "status": "dead_letter" if exhausted else "failed",
                "next_attempt_at": None
                if exhausted
                else (now + timedelta(seconds=self._policy.retry_delay_seconds)).isoformat(),
                "error_code": f"outbox_publish_{type(exc).__name__}",
                "updated_at": now.isoformat(),
            }
        )
        self._store.replace(failed, expected_status="publishing")


def _utc_now() -> datetime:
    return datetime.now(UTC)
