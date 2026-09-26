from __future__ import annotations

from combo.dynamic_runtime.dispatcher import CommandOutcome
from combo.dynamic_runtime.policy_repositories import UserRuntimePolicyStore
from combo.runtime_protocol import (
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
    ) -> CommandOutcome:
        del receipt
        payload = envelope.payload
        if not isinstance(payload, SetExecutionPreferencePayload):
            raise ValueError("execution preference handler received a different command kind")
        try:
            self._policies.write(
                principal_id=envelope.principal_id,
                expected_revision=payload.expected_policy_revision,
                changes={
                    "execution_preference": payload.execution_preference,
                    "approval_mode": payload.approval_mode,
                },
            )
        except RuntimeError as exc:
            if str(exc) != "runtime_policy_revision_conflict":
                raise
            return CommandOutcome(
                status="rejected",
                rejection_code="runtime_policy_revision_conflict",
            )
        return CommandOutcome(status="completed")
