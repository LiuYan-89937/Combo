from __future__ import annotations

import asyncio
from uuid import uuid4

from combo.dynamic_runtime.dispatcher import CommandOutcome
from combo.dynamic_runtime.capability_resolver import MainTurnCapabilityResolver, MainTurnCapabilityResolverProtocol
from combo.dynamic_runtime.delegated_model_selector import DelegatedTaskModelSelector
from combo.dynamic_runtime.delegation_policy import MAIN_RUNTIME_ONLY_CAPABILITY_IDS
from combo.dynamic_runtime.model_service import ResolvedRuntimePolicy, RuntimeModelResolver
from combo.dynamic_runtime.policy_repositories import UserRuntimePolicyStore
from combo.dynamic_runtime.repositories import ConversationStore, RuntimeInstanceStore, utc_now_text
from combo.dynamic_runtime.runtime_service import DynamicRuntimeService
from combo.dynamic_runtime.runtime_start import RuntimeStartStore
from combo.runtime_protocol import (
    CommandEnvelope,
    CommandReceipt,
    RuntimeInstance,
    RuntimeRequest,
    SendMessagePayload,
)


class MainTurnCommandHandler:
    """Create and execute one main turn from dynamic runtime authorities."""

    def __init__(
        self,
        *,
        conversations: ConversationStore,
        runtime_instances: RuntimeInstanceStore,
        runtime_policies: UserRuntimePolicyStore,
        model_resolver: RuntimeModelResolver,
        capability_resolver: MainTurnCapabilityResolverProtocol,
        runtime_starts: RuntimeStartStore,
        runtime_service: DynamicRuntimeService,
        delegated_model_selector: DelegatedTaskModelSelector | None = None,
    ) -> None:
        self._conversations = conversations
        self._runtime_instances = runtime_instances
        self._runtime_policies = runtime_policies
        self._model_resolver = model_resolver
        self._capability_resolver = capability_resolver
        self._runtime_starts = runtime_starts
        self._runtime_service = runtime_service
        self._delegated_model_selector = delegated_model_selector

    async def handle(
        self,
        envelope: CommandEnvelope,
        receipt: CommandReceipt,
    ) -> CommandOutcome:
        payload = envelope.payload
        if not isinstance(payload, SendMessagePayload):
            raise ValueError("main turn handler only accepts send_message commands")
        conversation = self._conversations.require_identity(envelope.session_id)
        if conversation.status != "active":
            raise LookupError(f"active conversation not found: {envelope.session_id}")
        if conversation.principal_id != envelope.principal_id:
            raise PermissionError("command principal does not own the conversation")

        turn = self._conversations.require_turn_for_message(
            session_id=envelope.session_id,
            message_id=payload.message_id,
        )
        user_message = self._conversations.require_message(
            session_id=envelope.session_id,
            message_id=payload.message_id,
        )
        if turn.source_command_id != envelope.command_id:
            raise RuntimeError("prepared conversation turn belongs to a different command")
        if turn.status != "queued" or turn.active_runtime_instance_id is not None:
            raise RuntimeError("prepared conversation turn is not available for runtime attachment")

        try:
            policy = self._runtime_policies.require_for_principal(envelope.principal_id)
            resolved_policy = self._model_resolver.resolve_policy(
                policy,
                operation="main_turn",
                execution_preference=payload.execution_preference,
                approval_mode=payload.approval_mode,
            )
            if payload.scheduler_run_id is not None:
                selector = self._delegated_model_selector
                if selector is None:
                    raise RuntimeError("scheduled agent model selector is unavailable")
                selected = selector.select(
                    task_description=payload.content,
                    strategy=payload.execution_preference or policy.execution_preference,
                    fallback_profile_id=str(policy.model_profile_id or ""),
                )
                selected_model = self._model_resolver.resolve_chat_model(
                    operation="main_turn",
                    profile_id=selected.profile_id,
                    reasoning_intensity=policy.reasoning_intensity,
                )
                resolved_policy = ResolvedRuntimePolicy(
                    snapshot=resolved_policy.snapshot.model_copy(update={"model": selected_model.snapshot}),
                    chat_model=selected_model,
                )
        except Exception:
            self._conversations.fail_pre_runtime_turn(source_command_id=envelope.command_id)
            return CommandOutcome(
                status="rejected",
                rejection_code="runtime_policy_resolution_failed",
            )
        try:
            if payload.scheduler_run_id is not None:
                resolver = self._capability_resolver
                if not isinstance(resolver, MainTurnCapabilityResolver):
                    raise RuntimeError("scheduled agent capability resolver is unavailable")
                capability_snapshot = resolver.resolve_requirements(
                    principal_id=envelope.principal_id,
                    requirements=(),
                    policy=resolved_policy,
                    workspace_id=conversation.workspace_id,
                    include_system_capabilities=True,
                    excluded_capability_ids=MAIN_RUNTIME_ONLY_CAPABILITY_IDS,
                )
            else:
                capability_snapshot = await self._capability_resolver.resolve(
                    envelope=envelope,
                    policy=resolved_policy,
                    workspace_id=conversation.workspace_id,
                )
        except asyncio.CancelledError:
            self._conversations.cancel_pre_runtime_turn(source_command_id=envelope.command_id)
            raise
        except Exception:
            self._conversations.fail_pre_runtime_turn(source_command_id=envelope.command_id)
            return CommandOutcome(
                status="rejected",
                rejection_code="capability_resolution_failed",
            )

        now = utc_now_text()
        runtime_instance_id = uuid4().hex
        request_id = uuid4().hex
        request = RuntimeRequest(
            request_id=request_id,
            principal_id=envelope.principal_id,
            session_id=envelope.session_id,
            turn_id=turn.turn_id,
            workspace_id=conversation.workspace_id,
            runtime_role="main",
            strategy=resolved_policy.snapshot.execution_preference,
            policy_snapshot=resolved_policy.snapshot,
            capability_snapshot_id=capability_snapshot.snapshot_id,
            approval_mode=resolved_policy.snapshot.approval_mode,
            force_collaboration=payload.force_collaboration,
            task_revision=turn.task_revision,
            scheduler_run_id=payload.scheduler_run_id,
            created_at=now,
        )
        instance = RuntimeInstance(
            runtime_instance_id=runtime_instance_id,
            request=request,
            capability_snapshot_id=capability_snapshot.snapshot_id,
            status="queued",
            stream_id=f"runtime:{runtime_instance_id}",
            last_event_sequence=1,
            created_at=now,
            updated_at=now,
        )
        attached_turn = turn.model_copy(
            update={
                "active_runtime_instance_id": runtime_instance_id,
                "updated_at": now,
            }
        )
        self._runtime_starts.attach(
            envelope=envelope,
            claimed_receipt=receipt,
            turn=attached_turn,
            user_message=user_message,
            capability_snapshot=capability_snapshot,
            runtime_instance=instance,
        )

        try:
            result = await asyncio.to_thread(self._runtime_service.execute, runtime_instance_id)
        except Exception:
            failed = self._runtime_instances.get(runtime_instance_id)
            if failed.status == "cancelled" and failed.error is not None:
                return CommandOutcome(
                    status="cancelled",
                    request_id=request_id,
                    runtime_instance_id=runtime_instance_id,
                    error=failed.error,
                )
            if failed.status != "failed" or failed.error is None:
                raise
            return CommandOutcome(
                status="failed",
                request_id=request_id,
                runtime_instance_id=runtime_instance_id,
                error=failed.error,
            )

        command_status = "cancelled" if result.status == "cancelled" else "completed"
        return CommandOutcome(
            status=command_status,
            request_id=request_id,
            runtime_instance_id=runtime_instance_id,
            error=result.runtime_instance.error,
        )
