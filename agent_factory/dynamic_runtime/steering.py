from __future__ import annotations

from agent_factory.dynamic_runtime.dispatcher import CommandOutcome
from agent_factory.dynamic_runtime.repositories import CommandInbox, RuntimeInstanceStore
from agent_factory.dynamic_runtime.run_control import RuntimeInputInjection, RuntimeRunControlRegistry
from agent_factory.runtime_protocol import (
    CommandEnvelope,
    CommandReceipt,
    SteerRuntimeRequestPayload,
)


class SteerRuntimeCommandHandler:
    """Deliver one queued user message into the active main runtime."""

    def __init__(
        self,
        *,
        commands: CommandInbox,
        runtime_instances: RuntimeInstanceStore,
        run_controls: RuntimeRunControlRegistry,
    ) -> None:
        self._commands = commands
        self._runtime_instances = runtime_instances
        self._run_controls = run_controls

    async def handle(
        self,
        envelope: CommandEnvelope,
        receipt: CommandReceipt,
        *,
        generation: int,
    ) -> CommandOutcome:
        del receipt, generation
        payload = envelope.payload
        if not isinstance(payload, SteerRuntimeRequestPayload):
            raise ValueError("steer runtime handler received a different command kind")
        message = self._commands.queued_message_payload(
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
            return CommandOutcome(
                status="rejected",
                rejection_code="active_runtime_not_available_for_steering",
            )
        injection = RuntimeInputInjection(
            injection_id=payload.queued_command_id,
            role="user",
            content=message.content,
        )
        if not self._run_controls.submit_input(
            runtime_instance_id=active.runtime_instance_id,
            injection=injection,
        ):
            return CommandOutcome(
                status="rejected",
                rejection_code="active_runtime_not_accepting_steering",
            )
        try:
            self._commands.complete_queued_as_steering(
                command_id=payload.queued_command_id,
                principal_id=envelope.principal_id,
                session_id=envelope.session_id,
            )
        except Exception:
            self._run_controls.revoke_input(
                runtime_instance_id=active.runtime_instance_id,
                injection_id=injection.injection_id,
            )
            raise
        return CommandOutcome(status="completed")
