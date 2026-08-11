from __future__ import annotations

import asyncio
from typing import Awaitable, Protocol
from uuid import uuid4

from agent_factory.dynamic_runtime.dispatcher import CommandOutcome
from agent_factory.dynamic_runtime.capability_resolver import MainTurnCapabilityResolverProtocol
from agent_factory.dynamic_runtime.model_service import ResolvedRuntimePolicy, RuntimeModelResolver
from agent_factory.dynamic_runtime.policy_repositories import UserRuntimePolicyStore
from agent_factory.dynamic_runtime.repositories import ConversationStore, RuntimeInstanceStore, utc_now_text
from agent_factory.dynamic_runtime.runtime_service import DynamicRuntimeService
from agent_factory.dynamic_runtime.runtime_start import RuntimeStartStore
from agent_factory.runtime_protocol import (
    AttachmentPart,
    CommandEnvelope,
    CommandReceipt,
    ConversationMessage,
    ConversationTurn,
    RouteDecision,
    RuntimeInstance,
    RuntimeRequest,
    SendMessagePayload,
    TextPart,
)


class RouteAnalyzer(Protocol):
    def analyze(
        self,
        *,
        envelope: CommandEnvelope,
        payload: SendMessagePayload,
        policy: ResolvedRuntimePolicy,
    ) -> Awaitable[RouteDecision]:
        ...


class ExecutionRouter:
    """Honor explicit routing while retaining one semantic route analysis."""

    def __init__(self, analyzer: RouteAnalyzer) -> None:
        self._analyzer = analyzer

    async def route(
        self,
        *,
        envelope: CommandEnvelope,
        payload: SendMessagePayload,
        policy: ResolvedRuntimePolicy,
    ) -> RouteDecision:
        analyzed = await self._analyzer.analyze(
            envelope=envelope,
            payload=payload,
            policy=policy,
        )
        preference = policy.snapshot.execution_preference
        if preference == "auto":
            if analyzed.decision_source != "auto":
                raise ValueError("automatic route analyzer must return decision_source='auto'")
            return analyzed
        return analyzed.model_copy(
            update={
                "strategy": preference,
                "decision_source": "user",
            }
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
        execution_router: ExecutionRouter,
        capability_resolver: MainTurnCapabilityResolverProtocol,
        runtime_starts: RuntimeStartStore,
        runtime_service: DynamicRuntimeService,
    ) -> None:
        self._conversations = conversations
        self._runtime_instances = runtime_instances
        self._runtime_policies = runtime_policies
        self._model_resolver = model_resolver
        self._execution_router = execution_router
        self._capability_resolver = capability_resolver
        self._runtime_starts = runtime_starts
        self._runtime_service = runtime_service

    async def handle(
        self,
        envelope: CommandEnvelope,
        receipt: CommandReceipt,
        *,
        generation: int,
    ) -> CommandOutcome:
        payload = envelope.payload
        if not isinstance(payload, SendMessagePayload):
            raise ValueError("main turn handler only accepts send_message commands")
        conversation = self._conversations.require_identity(envelope.session_id)
        if conversation.status != "active":
            raise LookupError(f"active conversation not found: {envelope.session_id}")
        if conversation.principal_id != envelope.principal_id:
            raise PermissionError("command principal does not own the conversation")

        policy = self._runtime_policies.require_for_principal(envelope.principal_id)
        resolved_policy = self._model_resolver.resolve_policy(
            policy,
            operation="main_turn",
            execution_preference=payload.execution_preference,
            approval_mode=payload.approval_mode,
        )
        route = await self._execution_router.route(
            envelope=envelope,
            payload=payload,
            policy=resolved_policy,
        )
        capability_snapshot = await self._capability_resolver.resolve(
            envelope=envelope,
            route=route,
            policy=resolved_policy,
            workspace_id=conversation.workspace_id,
        )

        now = utc_now_text()
        turn_id = uuid4().hex
        runtime_instance_id = uuid4().hex
        request_id = uuid4().hex
        task_revision = self._conversations.next_task_revision(envelope.session_id)
        request = RuntimeRequest(
            request_id=request_id,
            principal_id=envelope.principal_id,
            session_id=envelope.session_id,
            turn_id=turn_id,
            workspace_id=conversation.workspace_id,
            runtime_role="main",
            strategy=route.strategy,
            route_decision=route,
            policy_snapshot=resolved_policy.snapshot,
            capability_snapshot_id=capability_snapshot.snapshot_id,
            approval_mode=resolved_policy.snapshot.approval_mode,
            task_revision=task_revision,
            created_at=now,
        )
        instance = RuntimeInstance(
            runtime_instance_id=runtime_instance_id,
            request=request,
            capability_snapshot_id=capability_snapshot.snapshot_id,
            generation=generation,
            status="queued",
            stream_id=f"runtime:{runtime_instance_id}",
            last_event_sequence=1,
            created_at=now,
            updated_at=now,
        )
        turn = ConversationTurn(
            turn_id=turn_id,
            session_id=envelope.session_id,
            user_message_id=payload.message_id,
            task_revision=task_revision,
            status="queued",
            active_runtime_instance_id=runtime_instance_id,
            created_at=now,
            updated_at=now,
        )
        message = ConversationMessage(
            message_id=payload.message_id,
            session_id=envelope.session_id,
            turn_id=turn_id,
            role="user",
            status="committed",
            parts=(
                TextPart(text=payload.content),
                *(AttachmentPart(attachment=attachment) for attachment in payload.attachments),
            ),
            created_at=envelope.submitted_at,
            committed_at=now,
        )
        self._runtime_starts.create(
            envelope=envelope,
            claimed_receipt=receipt,
            turn=turn,
            user_message=message,
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
