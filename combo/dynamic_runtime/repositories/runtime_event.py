from __future__ import annotations

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.repositories.shared import _required_text
from combo.runtime_protocol import RuntimeEvent


class RuntimeEventStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def after(self, *, stream_id: str, sequence: int = 0, limit: int = 500) -> list[RuntimeEvent]:
        if sequence < 0:
            raise ValueError("runtime event sequence cannot be negative")
        if limit < 1:
            raise ValueError("runtime event limit must be positive")
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select payload_json from runtime_events
                where stream_id = ? and sequence > ?
                order by sequence limit ?
                """,
                (_required_text(stream_id, "stream_id"), sequence, limit),
            ).fetchall()
        return [RuntimeEvent.model_validate_json(str(row["payload_json"])) for row in rows]

    def for_session(self, session_id: str, *, limit: int = 1000) -> list[RuntimeEvent]:
        if limit < 1:
            raise ValueError("runtime event limit must be positive")
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select payload_json from runtime_events
                where session_id = ? order by session_sequence limit ?
                """,
                (_required_text(session_id, "session_id"), limit),
            ).fetchall()
        return [RuntimeEvent.model_validate_json(str(row["payload_json"])) for row in rows]

    def after_event_id_for_session(
        self,
        *,
        session_id: str,
        after_event_id: str | None,
        limit: int = 1000,
    ) -> list[RuntimeEvent]:
        if limit < 1:
            raise ValueError("runtime event limit must be positive")
        cursor = self.session_sequence_for_event(
            session_id=session_id,
            event_id=after_event_id,
        )
        return self.after_session_sequence(
            session_id=session_id,
            session_sequence=cursor,
            limit=limit,
        )

    def session_sequence_for_event(
        self,
        *,
        session_id: str,
        event_id: str | None,
    ) -> int:
        session = _required_text(session_id, "session_id")
        if event_id is None:
            return 0
        value = _required_text(event_id, "event_id")
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select session_id, session_sequence from runtime_events where event_id = ?",
                (value,),
            ).fetchone()
        if row is None or str(row["session_id"]) != session:
            raise LookupError("runtime event cursor is unknown for this session")
        return int(row["session_sequence"])

    def latest_session_sequence(self, session_id: str) -> int:
        session = _required_text(session_id, "session_id")
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select coalesce(max(session_sequence), 0) from runtime_events where session_id = ?",
                (session,),
            ).fetchone()
        return int(row[0])

    def after_session_sequence(
        self,
        *,
        session_id: str,
        session_sequence: int,
        limit: int = 1000,
    ) -> list[RuntimeEvent]:
        if session_sequence < 0:
            raise ValueError("runtime session event sequence cannot be negative")
        if limit < 1:
            raise ValueError("runtime event limit must be positive")
        session = _required_text(session_id, "session_id")
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select payload_json from runtime_events
                where session_id = ? and session_sequence > ?
                order by session_sequence limit ?
                """,
                (session, session_sequence, limit),
            ).fetchall()
        return [RuntimeEvent.model_validate_json(str(row["payload_json"])) for row in rows]
