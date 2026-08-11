from __future__ import annotations

from agent_factory.dynamic_runtime.dispatcher import CommandOutcome
from agent_factory.dynamic_runtime.policy_repositories import UserRuntimePolicyStore
from agent_factory.dynamic_runtime.repositories import utc_now_text
from agent_factory.runtime_protocol import (
    CommandEnvelope,
    CommandReceipt,
    SetExecutionPreferencePayload,
)


class SetExecutionPreferenceCommandHandler:
    def __init__(self, policies: UserRuntimePolicyStore) -> None:
        self._policies = policies

    async def handle(
        self,
        envelope: CommandEnvelope,
        receipt: CommandReceipt,
        *,
        generation: int,
    ) -> CommandOutcome:
        del receipt, generation
        payload = envelope.payload
        if not isinstance(payload, SetExecutionPreferencePayload):
            raise ValueError("execution preference handler received a different command kind")
        current = self._policies.require_for_principal(envelope.principal_id)
        if current.revision != payload.expected_policy_revision:
            return CommandOutcome(
                status="rejected",
                rejection_code="runtime_policy_revision_conflict",
            )
        updated = current.model_copy(
            update={
                "revision": current.revision + 1,
                "execution_preference": payload.execution_preference,
                "approval_mode": payload.approval_mode,
                "updated_at": utc_now_text(),
            }
        )
        self._policies.replace(updated, expected_revision=current.revision)
        return CommandOutcome(status="completed")
