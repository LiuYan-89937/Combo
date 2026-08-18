from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.repositories import utc_now_text


class ConversationContextSnapshot(BaseModel):
    """Append-only model-context snapshot for one main-Agent conversation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str
    principal_id: str
    through_task_revision: int = Field(ge=1)
    graph_messages: tuple[dict[str, Any], ...]
    context_window: dict[str, Any]
    compression_report: dict[str, Any]
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator("snapshot_id", "session_id", "principal_id", "created_at")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("context snapshot identity must not be empty")
        return text

    @field_validator("graph_messages")
    @classmethod
    def _messages_are_present(
        cls,
        value: tuple[dict[str, Any], ...],
    ) -> tuple[dict[str, Any], ...]:
        if not value:
            raise ValueError("context snapshot requires graph messages")
        return value


class ConversationContextSnapshotStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def append(self, snapshot: ConversationContextSnapshot) -> None:
        with self._database.transaction() as connection:
            latest = connection.execute(
                """
                select through_task_revision
                from conversation_context_snapshots
                where session_id = ?
                order by created_at desc, rowid desc
                limit 1
                """,
                (snapshot.session_id,),
            ).fetchone()
            if latest is not None and int(latest["through_task_revision"]) > snapshot.through_task_revision:
                raise RuntimeError("context snapshot revision moved backwards")
            connection.execute(
                """
                insert into conversation_context_snapshots(
                  snapshot_id, session_id, principal_id, through_task_revision,
                  payload_json, created_at
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.session_id,
                    snapshot.principal_id,
                    snapshot.through_task_revision,
                    snapshot.model_dump_json(),
                    snapshot.created_at,
                ),
            )

    def latest(self, session_id: str) -> ConversationContextSnapshot | None:
        with self._database.connection(query_only=True) as connection:
            row = connection.execute(
                """
                select payload_json
                from conversation_context_snapshots
                where session_id = ?
                order by created_at desc, rowid desc
                limit 1
                """,
                (_required_text(session_id, "session_id"),),
            ).fetchone()
        if row is None:
            return None
        return ConversationContextSnapshot.model_validate_json(str(row["payload_json"]))


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
