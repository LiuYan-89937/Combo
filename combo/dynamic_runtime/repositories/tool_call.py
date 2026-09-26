from __future__ import annotations

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.persistence_helpers import insert_outbox
from combo.runtime_protocol import OutboxRecord, ToolCallRecord
from combo.runtime_protocol.tool_calls import ToolCallStatus
from combo.runtime_protocol.state_machines import TOOL_CALL_TRANSITIONS, require_transition


class ToolCallStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def create(self, record: ToolCallRecord, *, outbox: OutboxRecord) -> None:
        with self._database.transaction() as conn:
            conn.execute(
                """
                insert into tool_calls(
                  tool_call_id, runtime_instance_id, request_id, turn_id,
                  status, payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.tool_call_id,
                    record.runtime_instance_id,
                    record.request_id,
                    record.turn_id,
                    record.status,
                    record.model_dump_json(),
                    record.created_at,
                    record.updated_at,
                ),
            )
            insert_outbox(conn, outbox)

    def replace(self, record: ToolCallRecord, *, expected_status: ToolCallStatus, outbox: OutboxRecord) -> None:
        require_transition(expected_status, record.status, TOOL_CALL_TRANSITIONS, machine="tool call")
        with self._database.transaction() as conn:
            changed = conn.execute(
                """
                update tool_calls
                set status = ?, payload_json = ?, updated_at = ?
                where tool_call_id = ? and status = ?
                """,
                (
                    record.status,
                    record.model_dump_json(),
                    record.updated_at,
                    record.tool_call_id,
                    expected_status,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("tool call compare-and-set failed")
            insert_outbox(conn, outbox)
