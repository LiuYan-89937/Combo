from __future__ import annotations

from typing import Any, Protocol, Sequence
import logging

from combo.dynamic_runtime.dispatcher import CommandOutcome
from combo.dynamic_runtime.repositories import CommandInbox, RuntimeInstanceStore
from combo.dynamic_runtime.run_control import RuntimeInputInjection, RuntimeRunControlRegistry
from combo.runtime_protocol import (
    AttachmentRevisionRef,
    CommandEnvelope,
    CommandReceipt,
    SteerRuntimeRequestPayload,
)

logger = logging.getLogger(__name__)


class SteeringAttachmentResolver(Protocol):
    """Resolve a queued message's attachments into the active runtime scope."""

    def resolve_runtime_attachments(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        references: Sequence[AttachmentRevisionRef],
        runtime_instance_id: str,
    ) -> tuple[dict[str, Any], ...]:
        ...


class QueuedRuntimeInputDelivery:
    """Deliver a durable queued message at the active runtime's input boundary."""

    def __init__(
        self,
        *,
        commands: CommandInbox,
        runtime_instances: RuntimeInstanceStore,
        run_controls: RuntimeRunControlRegistry,
        attachments: SteeringAttachmentResolver | None = None,
    ) -> None:
        self._commands = commands
        self._runtime_instances = runtime_instances
        self._run_controls = run_controls
        self._attachments = attachments

    def _resolve_attachments(
        self,
        command_id: str,
        principal_id: str,
        active: Any,
        references: Sequence[AttachmentRevisionRef],
    ) -> tuple[dict[str, Any], ...]:
        """Import the queued message's attachments into the active runtime scope.

        Attachment resolution is best effort: a stale staged upload must not
        block the user's guidance, but the failure is logged instead of silently
        dropping the attachments.
        """
        resolved_references = tuple(references or ())
        if not resolved_references:
            return ()
        if self._attachments is None:
            logger.warning(
                "steering attachments were dropped because no resolver is configured: %s",
                command_id,
            )
            return ()
        request = active.request
        try:
            return self._attachments.resolve_runtime_attachments(
                principal_id=principal_id,
                workspace_id=request.workspace_id,
                references=resolved_references,
                runtime_instance_id=active.runtime_instance_id,
            )
        except Exception:
            logger.warning(
                "steering attachments could not be resolved for command %s",
                command_id,
                exc_info=True,
            )
            return ()

    def deliver(
        self,
        *,
        command_id: str,
        principal_id: str,
        session_id: str,
        interrupt_active: bool,
        target_runtime_instance_id: str | None = None,
    ) -> CommandOutcome:
        message, target_receipt = self._commands.message_command_payload(
            command_id=command_id,
            principal_id=principal_id,
            session_id=session_id,
        )

        # The work lane may claim the target after the user submits it but before
        # this control command runs.  In that case the message has already become
        # the active turn, so steering is satisfied without interrupting the new
        # runtime itself.
        if target_receipt.status == "running":
            return CommandOutcome(status="completed")
        if target_receipt.status != "queued":
            return CommandOutcome(
                status="rejected",
                rejection_code="steering_target_not_active",
            )
        try:
            active = (
                self._runtime_instances.get(target_runtime_instance_id)
                if target_runtime_instance_id is not None
                else self._runtime_instances.active_main_for_session(
                    session_id=session_id, principal_id=principal_id,
                )
            )
            if (active.request.session_id != session_id
                    or active.request.principal_id != principal_id
                    or active.status != "running"):
                raise LookupError("target runtime is not active in this conversation")
        except LookupError:
            return CommandOutcome(
                status="rejected",
                rejection_code="active_runtime_not_available_for_steering",
            )
        content = str(message.content or "").strip()
        attachments = self._resolve_attachments(command_id, principal_id, active, message.attachments)
        if not content and not attachments:
            # An attachment-only message whose files can no longer be imported has
            # nothing left to steer with; keep it queued instead of injecting an
            # empty turn.
            return CommandOutcome(
                status="rejected",
                rejection_code="steering_content_unavailable",
            )
        injection = RuntimeInputInjection(
            injection_id=message.message_id,
            role="user",
            content=content,
            attachments=attachments,
            updates_current_user_input=message.visibility != "internal",
        )

        def acknowledge_checkpoint(messages: list[Any]) -> None:
            position = next(index for index, item in enumerate(messages) if item.id == injection.injection_id)
            predecessor = next(
                (item for item in reversed(messages[:position])
                 if getattr(item, "type", None) in {"human", "ai"} and item.id),
                None,
            )
            if predecessor is None:
                raise RuntimeError("steered input has no conversation predecessor")
            self._commands.complete_queued_as_steering(
                command_id=command_id,
                principal_id=principal_id,
                session_id=session_id,
                runtime_instance_id=active.runtime_instance_id,
                after_message_id=str(predecessor.id),
            )

        def release_pending() -> None:
            self._commands.set_pending_steering(
                command_id=command_id,
                principal_id=principal_id,
                session_id=session_id,
                runtime_instance_id=None,
            )

        if not self._commands.set_pending_steering(
            command_id=command_id,
            principal_id=principal_id,
            session_id=session_id,
            runtime_instance_id=active.runtime_instance_id,
        ):
            return CommandOutcome(status="rejected", rejection_code="steering_target_not_active")
        if not self._run_controls.submit_input(
            runtime_instance_id=active.runtime_instance_id,
            injection=injection,
            on_checkpointed=acknowledge_checkpoint,
            on_discarded=release_pending,
        ):
            release_pending()
            return CommandOutcome(
                status="rejected",
                rejection_code="active_runtime_not_accepting_steering",
            )
        if not interrupt_active:
            return CommandOutcome(status="completed")
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
            release_pending()
            return CommandOutcome(
                status="rejected",
                rejection_code="active_runtime_not_available_for_steering",
            )
        return CommandOutcome(status="completed")


class SteerRuntimeCommandHandler:
    """User steering uses the shared delivery path and interrupts active work."""

    def __init__(self, *, commands: CommandInbox, runtime_instances: RuntimeInstanceStore,
                 run_controls: RuntimeRunControlRegistry,
                 attachments: SteeringAttachmentResolver | None = None) -> None:
        self._delivery = QueuedRuntimeInputDelivery(
            commands=commands, runtime_instances=runtime_instances,
            run_controls=run_controls, attachments=attachments,
        )

    async def handle(self, envelope: CommandEnvelope, receipt: CommandReceipt) -> CommandOutcome:
        del receipt
        payload = envelope.payload
        if not isinstance(payload, SteerRuntimeRequestPayload):
            raise ValueError("steer runtime handler received a different command kind")
        return self._delivery.deliver(
            command_id=payload.queued_command_id, principal_id=envelope.principal_id,
            session_id=envelope.session_id, interrupt_active=True,
        )
