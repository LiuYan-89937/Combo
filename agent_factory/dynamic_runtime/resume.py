from __future__ import annotations

import asyncio

from agent_factory.dynamic_runtime.dispatcher import CommandOutcome
from agent_factory.dynamic_runtime.repositories import RuntimeInstanceStore
from agent_factory.dynamic_runtime.runtime_service import DynamicRuntimeService
from agent_factory.runtime_protocol import (
    CommandEnvelope,
    CommandReceipt,
    ResumeInterruptPayload,
)


class ResumeInterruptCommandHandler:
    def __init__(
        self,
        *,
        runtime_instances: RuntimeInstanceStore,
        runtime_service: DynamicRuntimeService,
    ) -> None:
        self._runtime_instances = runtime_instances
        self._runtime_service = runtime_service

    async def handle(
        self,
        envelope: CommandEnvelope,
        receipt: CommandReceipt,
        *,
        generation: int,
    ) -> CommandOutcome:
        del receipt, generation
        payload = envelope.payload
        if not isinstance(payload, ResumeInterruptPayload):
            raise ValueError("resume handler received a different command kind")
        current = self._runtime_instances.get(payload.runtime_instance_id)
        if current.request.request_id != payload.request_id:
            return CommandOutcome(status="rejected", rejection_code="runtime_request_mismatch")
        if (
            current.request.session_id != envelope.session_id
            or current.request.principal_id != envelope.principal_id
        ):
            return CommandOutcome(status="rejected", rejection_code="runtime_owner_mismatch")
        if current.status not in {"waiting_approval", "waiting_external"}:
            return CommandOutcome(status="rejected", rejection_code="runtime_not_waiting")
        resume_payload = {
            "interrupt_id": payload.interrupt_id,
            "decision": payload.decision,
            **({"response": payload.response} if payload.response is not None else {}),
        }
        try:
            result = await asyncio.to_thread(
                self._runtime_service.resume,
                payload.runtime_instance_id,
                resume_payload=resume_payload,
            )
        except Exception:
            terminal = self._runtime_instances.get(payload.runtime_instance_id)
            if terminal.status in {"failed", "cancelled"} and terminal.error is not None:
                return CommandOutcome(
                    status=terminal.status,
                    request_id=payload.request_id,
                    runtime_instance_id=payload.runtime_instance_id,
                    error=terminal.error,
                )
            raise
        return CommandOutcome(
            status="cancelled" if result.status == "cancelled" else "completed",
            request_id=payload.request_id,
            runtime_instance_id=payload.runtime_instance_id,
            error=result.runtime_instance.error,
        )
