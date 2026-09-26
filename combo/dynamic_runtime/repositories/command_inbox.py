from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.persistence_helpers import (
    advance_conversation_revision,
    cancel_undelivered_turn,
    insert_message,
    insert_outbox,
    insert_turn,
)
from combo.dynamic_runtime.repositories.shared import CONTROL_COMMAND_KINDS, _required_text, utc_now_text
from combo.runtime_protocol import (
    AttachmentPart,
    CommandEnvelope,
    CommandReceipt,
    ConversationMessage,
    ConversationTurn,
    OutboxRecord,
    SendMessagePayload,
    TextPart,
)
from combo.runtime_protocol.state_machines import (
    COMMAND_TRANSITIONS,
    CONVERSATION_TURN_TRANSITIONS,
    require_transition,
)
from combo.runtime_protocol.conversation import SteeringPlacement


class MessageAlreadyBeingSteered(ValueError):
    """The runtime owns this input; cancelling its queued record cannot retract it."""


class CommandInbox:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def accept(self, envelope: CommandEnvelope, receipt: CommandReceipt) -> CommandReceipt:
        if receipt.status != "received" or receipt.receipt_revision != 1:
            raise ValueError("new command receipt must start at received revision 1")
        if envelope.command_id != receipt.command_id:
            raise ValueError("command envelope and receipt IDs do not match")
        if envelope.client_instance_id != receipt.client_instance_id:
            raise ValueError("command envelope and receipt client identities do not match")
        if envelope.principal_id != receipt.principal_id or envelope.session_id != receipt.session_id:
            raise ValueError("command envelope and receipt ownership does not match")
        envelope_json = envelope.model_dump_json()
        with self._database.transaction() as conn:
            existing = conn.execute(
                "select envelope_json, receipt_json from command_inbox where command_id = ?",
                (envelope.command_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["envelope_json"]) != envelope_json:
                    raise ValueError("command_id was already submitted with a different envelope")
                return CommandReceipt.model_validate_json(str(existing["receipt_json"]))
            queued = receipt.model_copy(
                update={
                    "status": "queued",
                    "receipt_revision": 2,
                    "updated_at": utc_now_text(),
                }
            )
            sequence = int(
                conn.execute("select coalesce(max(queue_sequence), 0) + 1 from command_inbox").fetchone()[0]
            )
            conn.execute(
                """
                insert into command_inbox(
                  command_id, client_instance_id, principal_id, session_id, status,
                  receipt_revision, envelope_json, receipt_json, queue_sequence,
                  received_at, updated_at, terminal_at, command_kind
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.command_id,
                    receipt.client_instance_id,
                    receipt.principal_id,
                    receipt.session_id,
                    queued.status,
                    queued.receipt_revision,
                    envelope_json,
                    queued.model_dump_json(),
                    sequence,
                    receipt.received_at,
                    queued.updated_at,
                    queued.terminal_at,
                    envelope.payload.kind,
                ),
            )
            if isinstance(envelope.payload, SendMessagePayload):
                _insert_send_message_intake(conn, envelope)
            queue_position = int(
                conn.execute(
                    """
                    select count(*) from command_inbox
                    where session_id = ? and command_id <> ?
                      and command_kind = 'send_message'
                      and status in ('queued', 'running')
                      and queue_sequence < ?
                    """,
                    (envelope.session_id, envelope.command_id, sequence),
                ).fetchone()[0]
            )
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="command",
                    aggregate_id=queued.command_id,
                    aggregate_revision=queued.receipt_revision,
                    event_id=f"command:{queued.command_id}:{queued.receipt_revision}",
                    event_kind="command_queued",
                    payload={
                        **queued.model_dump(mode="json"),
                        "command_kind": envelope.payload.kind,
                        "request_source": (
                            "internal"
                            if isinstance(envelope.payload, SendMessagePayload)
                            and envelope.payload.visibility == "internal"
                            else "user"
                        ),
                        "dispatch_state": "queued" if queue_position else "dispatching",
                        "queue_position": queue_position,
                        "queue_sequence": sequence,
                    },
                    created_at=queued.updated_at,
                    updated_at=queued.updated_at,
                ),
            )
        return queued

    def queued_message_payload(
        self,
        *,
        command_id: str,
        principal_id: str,
        session_id: str,
    ) -> SendMessagePayload:
        payload, receipt = self.message_command_payload(
            command_id=command_id,
            principal_id=principal_id,
            session_id=session_id,
        )
        if receipt.status != "queued":
            raise ValueError(f"message command is not queued: {command_id}")
        return payload

    def message_command_payload(
        self,
        *,
        command_id: str,
        principal_id: str,
        session_id: str,
    ) -> tuple[SendMessagePayload, CommandReceipt]:
        target_id = _required_text(command_id, "command_id")
        owner = _required_text(principal_id, "principal_id")
        session = _required_text(session_id, "session_id")
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select receipt_json, envelope_json from command_inbox
                where command_id = ? and principal_id = ? and session_id = ?
                  and command_kind = 'send_message'
                """,
                (target_id, owner, session),
            ).fetchone()
            if row is None:
                raise LookupError(f"message command not found: {target_id}")
            receipt = CommandReceipt.model_validate_json(str(row["receipt_json"]))
            envelope = CommandEnvelope.model_validate_json(str(row["envelope_json"]))
            if not isinstance(envelope.payload, SendMessagePayload):
                raise TypeError("steering target is not a send-message command")
        return envelope.payload, receipt

    def set_pending_steering(
        self, *, command_id: str, principal_id: str, session_id: str,
        runtime_instance_id: str | None,
    ) -> bool:
        """Reserve/release a queued turn without claiming a second execution."""
        with self._database.transaction() as conn:
            row = conn.execute(
                """
                select command.receipt_json, turn.payload_json
                from command_inbox command join conversation_turns turn
                  on json_extract(turn.payload_json, '$.source_command_id') = command.command_id
                where command.command_id = ? and command.principal_id = ?
                  and command.session_id = ? and command.status = 'queued'
                """,
                (command_id, principal_id, session_id),
            ).fetchone()
            if row is None:
                return False
            receipt = CommandReceipt.model_validate_json(str(row["receipt_json"]))
            turn = ConversationTurn.model_validate_json(str(row["payload_json"]))
            if turn.steering is not None and turn.steering.after_message_id is not None:
                return False
            if runtime_instance_id is not None:
                active = conn.execute(
                    """
                    select 1 from runtime_instances where runtime_instance_id = ?
                      and session_id = ? and status = 'running'
                      and json_extract(payload_json, '$.request.principal_id') = ?
                    """, (runtime_instance_id, session_id, principal_id),
                ).fetchone()
                if active is None:
                    return False
            placement = SteeringPlacement(runtime_instance_id=runtime_instance_id) if runtime_instance_id else None
            if turn.steering == placement:
                return True
            now = utc_now_text()
            updated = turn.model_copy(update={"steering": placement, "updated_at": now})
            conn.execute(
                "update conversation_turns set payload_json = ?, updated_at = ? where turn_id = ?",
                (updated.model_dump_json(), now, turn.turn_id),
            )
            insert_outbox(conn, OutboxRecord(
                aggregate_kind="command", aggregate_id=command_id,
                aggregate_revision=receipt.receipt_revision,
                event_id=f"command:{command_id}:steering:{uuid4().hex}",
                event_kind="command_steering_started" if placement else "command_steering_rejected",
                payload={
                    **receipt.model_dump(mode="json"), "queued_command_id": command_id,
                    "steering": placement.model_dump(mode="json") if placement else None,
                },
                created_at=now, updated_at=now,
            ))
            advance_conversation_revision(conn, session_id, updated_at=now)
            return True

    def complete_queued_as_steering(
        self,
        *,
        command_id: str,
        principal_id: str,
        session_id: str,
        runtime_instance_id: str,
        after_message_id: str,
    ) -> CommandReceipt:
        target_id = _required_text(command_id, "command_id")
        owner = _required_text(principal_id, "principal_id")
        session = _required_text(session_id, "session_id")
        with self._database.transaction() as conn:
            row = conn.execute(
                """
                select receipt_json, envelope_json from command_inbox
                where command_id = ? and principal_id = ? and session_id = ?
                  and command_kind = 'send_message'
                """,
                (target_id, owner, session),
            ).fetchone()
            if row is None:
                raise LookupError(f"message command not found: {target_id}")
            receipt = CommandReceipt.model_validate_json(str(row["receipt_json"]))
            if receipt.status != "queued":
                # Cancellation may settle the queued command before acknowledgement.
                # Never rewrite a terminal command from a late graph checkpoint.
                return receipt
            now = utc_now_text()
            completed = receipt.model_copy(
                update={
                    "status": "completed",
                    "receipt_revision": receipt.receipt_revision + 1,
                    "updated_at": now,
                    "terminal_at": now,
                }
            )
            changed = conn.execute(
                """
                update command_inbox
                set status = 'completed', receipt_revision = ?, receipt_json = ?,
                    updated_at = ?, terminal_at = ?
                where command_id = ? and status = 'queued' and receipt_revision = ?
                """,
                (
                    completed.receipt_revision,
                    completed.model_dump_json(),
                    now,
                    now,
                    target_id,
                    receipt.receipt_revision,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("queued steering command compare-and-set failed")
            turn_row = conn.execute(
                """
                select payload_json from conversation_turns
                where json_extract(payload_json, '$.source_command_id') = ?
                """,
                (target_id,),
            ).fetchone()
            if turn_row is None:
                raise LookupError(f"conversation turn not found for command: {target_id}")
            turn = ConversationTurn.model_validate_json(str(turn_row["payload_json"]))
            require_transition(turn.status, "completed", CONVERSATION_TURN_TRANSITIONS, machine="conversation turn")
            placement = SteeringPlacement(runtime_instance_id=runtime_instance_id, after_message_id=after_message_id)
            completed_turn = turn.model_copy(
                update={"status": "completed", "updated_at": now, "terminal_at": now, "steering": placement}
            )
            turn_changed = conn.execute(
                """
                update conversation_turns
                set status = 'completed', payload_json = ?, updated_at = ?, terminal_at = ?
                where turn_id = ? and status = 'queued'
                """,
                (completed_turn.model_dump_json(), now, now, turn.turn_id),
            ).rowcount
            if turn_changed != 1:
                raise RuntimeError("queued steering turn compare-and-set failed")
            envelope = CommandEnvelope.model_validate_json(str(row["envelope_json"]))
            if isinstance(envelope.payload, SendMessagePayload) and envelope.payload.notification_event_ids:
                event_ids = envelope.payload.notification_event_ids
                placeholders = ",".join("?" for _ in event_ids)
                # The graph has checkpointed this input. Acknowledge its
                # notification in the same transaction as the queued turn, so
                # recovery cannot dispatch the result as a second turn.
                conn.execute(
                    f"""
                    update delegated_task_notifications
                    set delivered_runtime_instance_id = ?, delivered_at = ?
                    where principal_id = ? and session_id = ?
                      and event_id in ({placeholders})
                      and delivered_runtime_instance_id is null
                    """,
                    (runtime_instance_id, now, owner, session, *event_ids),
                )
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="command",
                    aggregate_id=target_id,
                    aggregate_revision=completed.receipt_revision,
                    event_id=f"command:{target_id}:steering:{uuid4().hex}",
                    event_kind="command_steering",
                    payload={
                        **completed.model_dump(mode="json"),
                        "command_kind": "send_message",
                        "dispatch_state": "promoted",
                        "steering": placement.model_dump(mode="json"),
                    },
                    created_at=now,
                    updated_at=now,
                ),
            )
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="conversation",
                    aggregate_id=session,
                    aggregate_revision=turn.task_revision,
                    event_id=f"conversation:{session}:turn:{turn.turn_id}:steered",
                    event_kind="conversation_turn_completed",
                    payload={
                        "session_id": session,
                        "turn_id": turn.turn_id,
                        "command_id": target_id,
                        "status": "completed",
                        "disposition": "steered",
                    },
                    created_at=now,
                    updated_at=now,
                ),
            )
            advance_conversation_revision(conn, session, updated_at=now)
        return completed

    def cancel_queued_message(
        self,
        *,
        command_id: str,
        principal_id: str,
        session_id: str,
    ) -> CommandReceipt:
        target_id = _required_text(command_id, "command_id")
        owner = _required_text(principal_id, "principal_id")
        session = _required_text(session_id, "session_id")
        with self._database.transaction() as conn:
            row = conn.execute(
                """
                select receipt_json from command_inbox
                where command_id = ? and principal_id = ? and session_id = ?
                  and command_kind = 'send_message'
                """,
                (target_id, owner, session),
            ).fetchone()
            if row is None:
                raise LookupError(f"queued message command not found: {target_id}")
            receipt = CommandReceipt.model_validate_json(str(row["receipt_json"]))
            if receipt.status != "queued":
                return receipt
            turn_row = conn.execute(
                """
                select payload_json from conversation_turns
                where session_id = ? and json_extract(payload_json, '$.source_command_id') = ?
                """,
                (session, target_id),
            ).fetchone()
            if turn_row is None:
                raise LookupError(f"conversation turn not found for command: {target_id}")
            turn = ConversationTurn.model_validate_json(str(turn_row["payload_json"]))
            # Reservation and cancellation share this transaction boundary. Once
            # handed to steering, the graph may already have consumed the input.
            if turn.steering is not None:
                raise MessageAlreadyBeingSteered(target_id)
            now = utc_now_text()
            cancel_undelivered_turn(conn, turn, updated_at=now)
            cancelled = receipt.model_copy(
                update={
                    "status": "cancelled",
                    "receipt_revision": receipt.receipt_revision + 1,
                    "updated_at": now,
                    "terminal_at": now,
                }
            )
            changed = conn.execute(
                """
                update command_inbox
                set status = 'cancelled', receipt_revision = ?, receipt_json = ?,
                    updated_at = ?, terminal_at = ?
                where command_id = ? and status = 'queued' and receipt_revision = ?
                """,
                (
                    cancelled.receipt_revision,
                    cancelled.model_dump_json(),
                    now,
                    now,
                    target_id,
                    receipt.receipt_revision,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("queued message cancellation compare-and-set failed")
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="command",
                    aggregate_id=target_id,
                    aggregate_revision=cancelled.receipt_revision,
                    event_id=f"command:{target_id}:{cancelled.receipt_revision}",
                    event_kind="command_cancelled",
                    payload={**cancelled.model_dump(mode="json"), "command_kind": "send_message"},
                    created_at=now,
                    updated_at=now,
                ),
            )
        return cancelled

    def get_receipt(self, command_id: str) -> CommandReceipt:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select receipt_json from command_inbox where command_id = ?",
                (_required_text(command_id, "command_id"),),
            ).fetchone()
        if row is None:
            raise LookupError(f"command receipt not found: {command_id}")
        return CommandReceipt.model_validate_json(str(row["receipt_json"]))

    def claim_next(
        self,
        *,
        lane: Literal["work", "control"],
    ) -> tuple[CommandEnvelope, CommandReceipt] | None:
        with self._database.transaction() as conn:
            control_placeholders = ", ".join("?" for _ in CONTROL_COMMAND_KINDS)
            lane_filter = (
                f"queued.command_kind in ({control_placeholders})"
                if lane == "control"
                else f"queued.command_kind not in ({control_placeholders})"
            )
            row = conn.execute(
                f"""
                select * from command_inbox queued
                where queued.status = 'queued'
                  and {lane_filter}
                  and not exists (
                    select 1 from conversation_turns turn
                    where json_extract(turn.payload_json, '$.source_command_id') = queued.command_id
                      and json_extract(turn.payload_json, '$.steering.runtime_instance_id') is not null
                      and json_extract(turn.payload_json, '$.steering.after_message_id') is null
                  )
                  and (
                    queued.command_kind in ({control_placeholders})
                    or not exists (
                      select 1 from command_inbox active
                      where active.session_id = queued.session_id and active.status = 'running'
                    )
                  )
                order by
                  queued.queue_sequence
                limit 1
                """,
                (*CONTROL_COMMAND_KINDS, *CONTROL_COMMAND_KINDS),
            ).fetchone()
            if row is None:
                return None
            current = CommandReceipt.model_validate_json(str(row["receipt_json"]))
            require_transition(current.status, "running", COMMAND_TRANSITIONS, machine="command")
            updated = current.model_copy(
                update={
                    "status": "running",
                    "receipt_revision": current.receipt_revision + 1,
                    "updated_at": utc_now_text(),
                }
            )
            changed = conn.execute(
                """
                update command_inbox
                set status = 'running', receipt_revision = ?, receipt_json = ?,
                    updated_at = ?
                where command_id = ? and status = 'queued' and receipt_revision = ?
                """,
                (
                    updated.receipt_revision,
                    updated.model_dump_json(),
                    updated.updated_at,
                    updated.command_id,
                    current.receipt_revision,
                ),
            ).rowcount
            if changed != 1:
                return None
            envelope = CommandEnvelope.model_validate_json(str(row["envelope_json"]))
            return envelope, updated

    def replace_receipt(
        self,
        *,
        receipt: CommandReceipt,
        expected_revision: int,
        outbox: OutboxRecord,
    ) -> None:
        with self._database.transaction() as conn:
            row = conn.execute(
                "select receipt_json, command_kind from command_inbox where command_id = ?",
                (receipt.command_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"command receipt not found: {receipt.command_id}")
            current = CommandReceipt.model_validate_json(str(row["receipt_json"]))
            require_transition(current.status, receipt.status, COMMAND_TRANSITIONS, machine="command")
            if receipt.receipt_revision != expected_revision + 1:
                raise ValueError("command receipt revision must increase by one")
            changed = conn.execute(
                """
                update command_inbox
                set status = ?, receipt_revision = ?, receipt_json = ?, updated_at = ?, terminal_at = ?
                where command_id = ? and receipt_revision = ?
                """,
                (
                    receipt.status,
                    receipt.receipt_revision,
                    receipt.model_dump_json(),
                    receipt.updated_at,
                    receipt.terminal_at,
                    receipt.command_id,
                    expected_revision,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("command receipt compare-and-set failed")
            if row["command_kind"] == "send_message" and receipt.status == "cancelled" and receipt.runtime_instance_id is None:
                turn_row = conn.execute(
                    """
                    select payload_json from conversation_turns
                    where session_id = ? and json_extract(payload_json, '$.source_command_id') = ?
                    """,
                    (receipt.session_id, receipt.command_id),
                ).fetchone()
                if turn_row is None:
                    raise LookupError(f"conversation turn not found for command: {receipt.command_id}")
                turn = ConversationTurn.model_validate_json(str(turn_row["payload_json"]))
                cancel_undelivered_turn(conn, turn, updated_at=receipt.updated_at)
            insert_outbox(conn, outbox)


def _insert_send_message_intake(conn: Any, envelope: CommandEnvelope) -> None:
    payload = envelope.payload
    if not isinstance(payload, SendMessagePayload):
        raise TypeError("send-message intake requires SendMessagePayload")
    conversation = conn.execute(
        """
        select principal_id, status from conversations where session_id = ?
        """,
        (envelope.session_id,),
    ).fetchone()
    if conversation is None or str(conversation["status"]) != "active":
        raise LookupError(f"active conversation not found: {envelope.session_id}")
    if str(conversation["principal_id"]) != envelope.principal_id:
        raise PermissionError("command principal does not own the conversation")
    existing_message = conn.execute(
        "select 1 from conversation_messages where message_id = ?",
        (payload.message_id,),
    ).fetchone()
    if existing_message is not None:
        raise ValueError(f"message_id is already committed: {payload.message_id}")

    task_revision = int(
        conn.execute(
            """
            select coalesce(max(task_revision), 0) + 1
            from conversation_turns where session_id = ?
            """,
            (envelope.session_id,),
        ).fetchone()[0]
    )
    now = utc_now_text()
    turn = ConversationTurn(
        turn_id=uuid4().hex,
        session_id=envelope.session_id,
        user_message_id=payload.message_id,
        task_revision=task_revision,
        status="queued",
        source_command_id=envelope.command_id,
        created_at=now,
        updated_at=now,
    )
    message = ConversationMessage(
        message_id=payload.message_id,
        session_id=envelope.session_id,
        turn_id=turn.turn_id,
        role="user",
        status="committed",
        parts=(
            *((TextPart(text=payload.content),) if payload.content else ()),
            *(AttachmentPart(attachment=attachment) for attachment in payload.attachments),
        ),
        created_at=envelope.submitted_at,
        committed_at=now,
        visibility=payload.visibility,
        notification_event_ids=payload.notification_event_ids,
    )
    insert_turn(conn, turn)
    insert_message(conn, message)
    if payload.visibility == "public":
        prior_public_user_messages = int(
            conn.execute(
                """
                select count(*) from conversation_messages
                where session_id = ? and role = 'user'
                  and json_extract(payload_json, '$.visibility') = 'public'
                  and message_id <> ?
                """,
                (envelope.session_id, payload.message_id),
            ).fetchone()[0]
        )
        if prior_public_user_messages == 0 and payload.content:
            conn.execute(
                "update conversations set title = ? where session_id = ?",
                (_conversation_title(payload.content), envelope.session_id),
            )
    insert_outbox(
        conn,
        OutboxRecord(
            aggregate_kind="conversation",
            aggregate_id=envelope.session_id,
            aggregate_revision=task_revision,
            event_id=f"conversation:{envelope.session_id}:turn:{turn.turn_id}:committed",
            event_kind="conversation_user_message_committed",
            payload={
                "session_id": envelope.session_id,
                "turn_id": turn.turn_id,
                "message_id": message.message_id,
                "command_id": envelope.command_id,
                "task_revision": task_revision,
            },
            created_at=now,
            updated_at=now,
        ),
    )
    advance_conversation_revision(conn, envelope.session_id, updated_at=now)


def _conversation_title(content: str) -> str:
    return " ".join(_required_text(content, "content").split())
