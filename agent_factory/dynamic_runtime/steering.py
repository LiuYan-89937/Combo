from __future__ import annotations

from agent_factory.dynamic_runtime.cancellation import RuntimeCancellationStore
from agent_factory.dynamic_runtime.dispatcher import CommandExecutionRegistry, CommandOutcome
from agent_factory.dynamic_runtime.repositories import CommandInbox, RuntimeInstanceStore
from agent_factory.dynamic_runtime.run_control import RuntimeRunControlRegistry
from agent_factory.runtime_protocol import (
    CancelRuntimeRequestPayload,
    CommandEnvelope,
    CommandReceipt,
    SteerRuntimeRequestPayload,
)


class SteerRuntimeCommandHandler:
    """Promote one queued message and drain its active predecessor."""

    def __init__(
        self,
        *,
        commands: CommandInbox,
        runtime_instances: RuntimeInstanceStore,
        cancellations: RuntimeCancellationStore,
        run_controls: RuntimeRunControlRegistry,
        executions: CommandExecutionRegistry,
    ) -> None:
        self._commands = commands
        self._runtime_instances = runtime_instances
        self._cancellations = cancellations
        self._run_controls = run_controls
        self._executions = executions

    async def handle(
        self,
        envelope: CommandEnvelope,
        receipt: CommandReceipt,
        *,
        generation: int,
    ) -> CommandOutcome:
        del receipt
        payload = envelope.payload
        if not isinstance(payload, SteerRuntimeRequestPayload):
            raise ValueError("steer runtime handler received a different command kind")
        self._commands.promote_queued(
            command_id=payload.queued_command_id,
            principal_id=envelope.principal_id,
            session_id=envelope.session_id,
        )
        try:
            active = self._runtime_instances.active_main_for_session(
                session_id=envelope.session_id,
                principal_id=envelope.principal_id,
            )
        except LookupError:
            active_command = self._commands.running_unattached_for_session(
                principal_id=envelope.principal_id,
                session_id=envelope.session_id,
            )
            if not self._executions.cancel(
                active_command.command_id,
                reason="user_steered",
            ):
                return CommandOutcome(
                    status="rejected",
                    rejection_code="command_execution_not_active",
                )
            return CommandOutcome(status="completed")
        cancellation_payload = CancelRuntimeRequestPayload(
            runtime_instance_id=active.runtime_instance_id,
            request_id=active.request.request_id,
            reason="user_steered",
        )
        cancellation = self._cancellations.request(
            envelope=envelope.model_copy(update={"payload": cancellation_payload}),
            payload=cancellation_payload,
            generation=generation,
        )
        if cancellation.active_execution:
            self._run_controls.request_drain(
                runtime_instance_id=active.runtime_instance_id,
                reason="user_steered",
            )
        return CommandOutcome(
            status="completed",
            request_id=active.request.request_id,
            runtime_instance_id=active.runtime_instance_id,
        )
