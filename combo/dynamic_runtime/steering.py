from __future__ import annotations

from combo.dynamic_runtime.dispatcher import CommandOutcome
from combo.dynamic_runtime.repositories import CommandInbox, RuntimeInstanceStore
from combo.dynamic_runtime.run_control import RuntimeInputInjection, RuntimeRunControlRegistry
from combo.runtime_protocol import (
    CommandEnvelope,
    CommandReceipt,
    SteerRuntimeRequestPayload,
)


class SteerRuntimeCommandHandler:
    """Steer a queued message, including cancellation of a raced tool run."""

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
    ) -> CommandOutcome:
        del receipt
        payload = envelope.payload
        if not isinstance(payload, SteerRuntimeRequestPayload):
            raise ValueError("steer runtime handler received a different command kind")
        message, target_receipt = self._commands.message_command_payload(
            command_id=payload.queued_command_id,
            principal_id=envelope.principal_id,
            session_id=envelope.session_id,
        )

        # The target can be claimed by the work lane between the click and
        # this control command.  It is no longer eligible for injection into a
        # previous turn; cancel its active tool/runtime instead of reporting a
        # queued-state validation failure.
        if target_receipt.status == "running":
            runtime_instance_id = str(target_receipt.runtime_instance_id or "").strip()
            if runtime_instance_id:
                self._run_controls.request_tool_interrupt(
                    runtime_instance_id=runtime_instance_id,
                    reason="user_steered",
                )
                return CommandOutcome(status="completed")
            return CommandOutcome(
                status="rejected",
                rejection_code="steering_target_not_ready",
            )
        if target_receipt.status != "queued":
            return CommandOutcome(
                status="rejected",
                rejection_code="steering_target_not_active",
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

        def acknowledge_checkpoint() -> None:
            acknowledged = self._commands.complete_queued_as_steering(
                command_id=payload.queued_command_id,
                principal_id=envelope.principal_id,
                session_id=envelope.session_id,
            )
            # A target may have been claimed after the initial status check.
            # Cancel its active tool so the injected guidance is the only
            # continuation and the race cannot surface as a runtime failure.
            if acknowledged.status == "running" and acknowledged.runtime_instance_id:
                self._run_controls.request_tool_interrupt(
                    runtime_instance_id=acknowledged.runtime_instance_id,
                    reason="user_steered",
                )

        if not self._run_controls.submit_input(
            runtime_instance_id=active.runtime_instance_id,
            injection=injection,
            on_checkpointed=acknowledge_checkpoint,
        ):
            return CommandOutcome(
                status="rejected",
                rejection_code="active_runtime_not_accepting_steering",
            )
        self._run_controls.request_tool_interrupt(
            runtime_instance_id=active.runtime_instance_id,
            reason="user_steered",
        )
        if not self._run_controls.request_generation_interrupt(
            runtime_instance_id=active.runtime_instance_id,
        ):
            self._run_controls.revoke_input(
                runtime_instance_id=active.runtime_instance_id,
                injection_id=injection.injection_id,
            )
            return CommandOutcome(
                status="rejected",
                rejection_code="active_runtime_not_available_for_steering",
            )
        return CommandOutcome(status="completed")
