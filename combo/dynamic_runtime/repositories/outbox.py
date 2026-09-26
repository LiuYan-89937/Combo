from __future__ import annotations

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.repositories.shared import _required_text, utc_now_text
from combo.runtime_protocol import OutboxRecord


class OutboxStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def pending(self, *, limit: int = 100) -> list[OutboxRecord]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select payload_json from runtime_outbox
                where status in ('pending', 'failed')
                  and (next_attempt_at is null or next_attempt_at <= ?)
                order by created_at, rowid limit ?
                """,
                (utc_now_text(), limit),
            ).fetchall()
        return [OutboxRecord.model_validate_json(str(row["payload_json"])) for row in rows]

    def replace(self, record: OutboxRecord, *, expected_status: str) -> None:
        with self._database.transaction() as conn:
            changed = conn.execute(
                """
                update runtime_outbox
                set status = ?, payload_json = ?, publish_attempts = ?,
                    next_attempt_at = ?, published_at = ?, error_code = ?, updated_at = ?
                where outbox_id = ? and status = ?
                """,
                (
                    record.status,
                    record.model_dump_json(),
                    record.publish_attempts,
                    record.next_attempt_at,
                    record.published_at,
                    record.error_code,
                    record.updated_at,
                    record.outbox_id,
                    expected_status,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("outbox compare-and-set failed")

    def claim_next(self) -> OutboxRecord | None:
        now = utc_now_text()
        with self._database.transaction() as conn:
            row = conn.execute(
                """
                select payload_json from runtime_outbox
                where status in ('pending', 'failed')
                  and (next_attempt_at is null or next_attempt_at <= ?)
                order by created_at, rowid limit 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            current = OutboxRecord.model_validate_json(str(row["payload_json"]))
            claimed = current.model_copy(
                update={
                    "status": "publishing",
                    "publish_attempts": current.publish_attempts + 1,
                    "next_attempt_at": None,
                    "error_code": None,
                    "updated_at": now,
                }
            )
            changed = conn.execute(
                """
                update runtime_outbox
                set status = 'publishing', payload_json = ?, publish_attempts = ?,
                    next_attempt_at = null, error_code = null, updated_at = ?
                where outbox_id = ? and status = ? and publish_attempts = ?
                """,
                (
                    claimed.model_dump_json(),
                    claimed.publish_attempts,
                    claimed.updated_at,
                    claimed.outbox_id,
                    current.status,
                    current.publish_attempts,
                ),
            ).rowcount
            if changed != 1:
                return None
        return claimed

    def recover_publishing(self, *, error_code: str, retry_at: str) -> int:
        code = _required_text(error_code, "error_code")
        when = _required_text(retry_at, "retry_at")
        recovered = 0
        with self._database.transaction() as conn:
            rows = conn.execute(
                "select payload_json from runtime_outbox where status = 'publishing'"
            ).fetchall()
            for row in rows:
                current = OutboxRecord.model_validate_json(str(row["payload_json"]))
                updated = current.model_copy(
                    update={
                        "status": "failed",
                        "next_attempt_at": when,
                        "error_code": code,
                        "updated_at": utc_now_text(),
                    }
                )
                changed = conn.execute(
                    """
                    update runtime_outbox
                    set status = 'failed', payload_json = ?, next_attempt_at = ?,
                        error_code = ?, updated_at = ?
                    where outbox_id = ? and status = 'publishing'
                    """,
                    (
                        updated.model_dump_json(),
                        updated.next_attempt_at,
                        updated.error_code,
                        updated.updated_at,
                        updated.outbox_id,
                    ),
                ).rowcount
                recovered += changed
        return recovered
