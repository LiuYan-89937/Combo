from __future__ import annotations

from agent_factory.dynamic_runtime.dispatcher import CommandExecutionRegistry, CommandOutcome
from agent_factory.dynamic_runtime.repositories import CommandInbox
from agent_factory.runtime_protocol import (
    CancelCommandRequestPayload,
    CommandEnvelope,
    CommandReceipt,
)


class CancelCommandRequestHandler:
    def __init__(
        self,
        *,
        commands: CommandInbox,
        executions: CommandExecutionRegistry,
    ) -> None:
        self._commands = commands
        self._executions = executions

    async def handle(
        self,
        envelope: CommandEnvelope,
        receipt: CommandReceipt,
        *,
        generation: int,
    ) -> CommandOutcome:
        del receipt, generation
        payload = envelope.payload
        if not isinstance(payload, CancelCommandRequestPayload):
            raise ValueError("cancel command handler received a different command kind")
        target = self._commands.get_receipt(payload.target_command_id)
        if target.principal_id != envelope.principal_id or target.session_id != envelope.session_id:
            return CommandOutcome(status="rejected", rejection_code="command_owner_mismatch")
        if target.status in {"completed", "failed", "cancelled", "rejected"}:
            return CommandOutcome(status="completed")
        if target.status == "queued":
            self._commands.cancel_queued_message(
                command_id=target.command_id,
                principal_id=envelope.principal_id,
                session_id=envelope.session_id,
            )
            return CommandOutcome(status="completed")
        if target.status != "running" or target.runtime_instance_id is not None:
            return CommandOutcome(
                status="rejected",
                rejection_code="command_not_cancellable_before_runtime",
            )
        if not self._executions.cancel(payload.target_command_id, reason=payload.reason):
            return CommandOutcome(
                status="rejected",
                rejection_code="command_execution_not_active",
            )
        return CommandOutcome(status="completed")
