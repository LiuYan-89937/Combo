from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from threading import RLock
from typing import Any
from uuid import uuid4

from agent_factory.dynamic_runtime.capability_resolver import MainTurnCapabilityResolver
from agent_factory.dynamic_runtime.delegation_policy import MAIN_RUNTIME_ONLY_CAPABILITY_IDS
from agent_factory.dynamic_runtime.delegation_store import DelegationStore
from agent_factory.dynamic_runtime.delegated_model_selector import DelegatedTaskModelSelector
from agent_factory.dynamic_runtime.model_service import ResolvedRuntimePolicy, RuntimeModelResolver
from agent_factory.runtime_protocol import (
    DelegationGrant,
    ExecutionStrategy,
    RouteDecision,
    RuntimeInstance,
    RuntimeRequest,
    TaskEnvelope,
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    strategy: ExecutionStrategy
    agent_name: str
    system_prompt: str
    objective: str
    capability_names: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]


SHARED_WORKSPACE_WRITE_SCOPE = "."


@dataclass(frozen=True, slots=True)
class _BoundServices:
    delegations: DelegationStore
    model_resolver: RuntimeModelResolver
    model_selector: DelegatedTaskModelSelector
    capability_resolver: MainTurnCapabilityResolver
    generation: int


class DelegationRuntimeCoordinator:
    """Create single-level temporary runtimes from an active main runtime."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._services: _BoundServices | None = None

    def bind(
        self,
        *,
        delegations: DelegationStore,
        model_resolver: RuntimeModelResolver,
        model_selector: DelegatedTaskModelSelector,
        capability_resolver: MainTurnCapabilityResolver,
        generation: int,
    ) -> None:
        services = _BoundServices(
            delegations=delegations,
            model_resolver=model_resolver,
            model_selector=model_selector,
            capability_resolver=capability_resolver,
            generation=generation,
        )
        with self._lock:
            if self._services is not None:
                raise RuntimeError("delegation runtime coordinator is already bound")
            self._services = services

    def for_parent(self, parent: RuntimeInstance) -> "BoundDelegationRuntime":
        with self._lock:
            services = self._services
        if services is None:
            raise RuntimeError("delegation runtime coordinator is not bound")
        return BoundDelegationRuntime(parent=parent, services=services)


@dataclass(frozen=True, slots=True)
class BoundDelegationRuntime:
    parent: RuntimeInstance
    services: _BoundServices

    def delegate(self, request: DelegationRequest) -> dict[str, Any]:
        parent = self.parent
        if parent.request.runtime_role != "main":
            raise PermissionError("only the main runtime may create temporary agents")
        if parent.status != "running" or parent.attempt_id is None:
            raise RuntimeError("delegation requires an actively running parent runtime")

        now_value = datetime.now(UTC)
        now = now_value.isoformat()
        task_id = uuid4().hex
        grant_id = uuid4().hex
        child_runtime_id = uuid4().hex
        parent_policy = parent.request.policy_snapshot
        parent_model = parent_policy.model
        selected_model = self.services.model_selector.select(
            task_description=_delegated_task_description(request),
            strategy=request.strategy,
            fallback_profile_id=parent_model.profile_id,
        )
        child_model = self.services.model_resolver.resolve_chat_model(
            operation="temporary_turn",
            profile_id=selected_model.profile_id,
            expected_profile_revision=(
                parent_model.profile_revision
                if selected_model.source == "inherited"
                else None
            ),
            expected_credential_revision=(
                parent_model.credential_revision
                if selected_model.source == "inherited"
                else None
            ),
            reasoning_intensity=parent_policy.reasoning_intensity,
        )
        child_policy = parent_policy.model_copy(
            update={
                "snapshot_id": uuid4().hex,
                "model": child_model.snapshot,
                "created_at": now,
            }
        )
        resolved_policy = ResolvedRuntimePolicy(
            snapshot=child_policy,
            chat_model=child_model,
        )
        try:
            child_snapshot = self.services.capability_resolver.resolve_requirements(
                principal_id=parent.request.principal_id,
                requirements=request.capability_names,
                policy=resolved_policy,
                workspace_id=parent.request.workspace_id,
                include_system_capabilities=True,
                excluded_capability_ids=MAIN_RUNTIME_ONLY_CAPABILITY_IDS,
            )
        except Exception as exc:
            logger.exception(
                "Delegated capability assembly failed: parent_runtime_instance_id=%s capability_names=%s",
                parent.runtime_instance_id,
                request.capability_names,
            )
            raise RuntimeError(
                "Child capability assembly failed for the selected public names. Search the capability "
                "catalog again and retry with exact returned names. Do not provide IDs, revisions, digests, "
                "or evidence. If no optional capability is required, retry with an empty capability list."
            ) from exc
        route = RouteDecision(
            strategy=request.strategy,
            decision_source="user",
            intent="task",
            reason="temporary task delegated by the main runtime",
            capability_requirements=request.capability_names,
        )
        child_request = RuntimeRequest(
            request_id=uuid4().hex,
            principal_id=parent.request.principal_id,
            session_id=parent.request.session_id,
            turn_id=parent.request.turn_id,
            workspace_id=parent.request.workspace_id,
            runtime_role="temporary",
            strategy=route.strategy,
            route_decision=route,
            policy_snapshot=child_policy,
            capability_snapshot_id=child_snapshot.snapshot_id,
            approval_mode=parent.request.approval_mode,
            task_revision=1,
            parent_runtime_instance_id=parent.runtime_instance_id,
            task_id=task_id,
            delegation_grant_id=grant_id,
            created_at=now,
        )
        child_runtime = RuntimeInstance(
            runtime_instance_id=child_runtime_id,
            request=child_request,
            capability_snapshot_id=child_snapshot.snapshot_id,
            generation=self.services.generation,
            status="queued",
            stream_id=f"runtime:{child_runtime_id}",
            last_event_sequence=1,
            created_at=now,
            updated_at=now,
        )
        envelope = TaskEnvelope(
            task_id=task_id,
            principal_id=parent.request.principal_id,
            parent_runtime_instance_id=parent.runtime_instance_id,
            delegation_grant_id=grant_id,
            capability_snapshot_id=child_snapshot.snapshot_id,
            task_revision=1,
            parent_task_revision=parent.request.task_revision,
            strategy=request.strategy,
            agent_name=request.agent_name,
            system_prompt=_child_system_prompt(request.system_prompt),
            objective=request.objective,
            acceptance_criteria=request.acceptance_criteria,
            context_facts=(),
            workspace_id=parent.request.workspace_id,
            allowed_write_roots=(SHARED_WORKSPACE_WRITE_SCOPE,),
            capability_requirements=request.capability_names,
            selected_model_profile_id=child_model.snapshot.profile_id,
            model_selection_source=selected_model.source,
            model_selection_reason=selected_model.reason,
            approval_mode=parent.request.approval_mode,
            created_at=now,
        )
        grant = DelegationGrant(
            grant_id=grant_id,
            principal_id=parent.request.principal_id,
            parent_runtime_instance_id=parent.runtime_instance_id,
            child_runtime_instance_id=child_runtime_id,
            task_id=task_id,
            task_revision=1,
            parent_task_revision=parent.request.task_revision,
            parent_capability_snapshot_id=parent.capability_snapshot_id,
            child_capability_snapshot_id=child_snapshot.snapshot_id,
            workspace_id=parent.request.workspace_id,
            approval_mode=parent.request.approval_mode,
            allowed_write_roots=(SHARED_WORKSPACE_WRITE_SCOPE,),
            allowed_tool_aliases=child_snapshot.tool_ids,
            maximum_delegation_depth=0,
            remaining_delegation_depth=0,
            expires_at=(
                now_value + timedelta(seconds=parent_policy.delegation_grant_ttl_seconds)
            ).isoformat(),
            created_at=now,
        )
        self.services.delegations.create(
            envelope=envelope,
            grant=grant,
            capability_snapshot=child_snapshot,
            child_runtime=child_runtime,
            max_parallel_children=parent_policy.max_parallel_temporary_agents,
        )
        return {
            "status": "queued",
            "agent_name": request.agent_name,
            "objective": request.objective,
            "strategy": request.strategy,
            "capabilities": list(request.capability_names),
            "model": {
                "profile_id": child_model.snapshot.profile_id,
                "provider": child_model.snapshot.provider,
                "model_name": child_model.snapshot.model_name,
                "selection_source": selected_model.source,
                "reason": selected_model.reason,
            },
            "message": (
                "Temporary agent task accepted and its task capsule is available. "
                "Do not poll it; completion and interaction updates are delivered asynchronously."
            ),
        }

    def status(self) -> dict[str, Any]:
        records = self.services.delegations.list_for_session(
            principal_id=self.parent.request.principal_id,
            session_id=self.parent.request.session_id,
            task_id=None,
        )
        return {
            "tasks": [
                {
                    "agent_name": record.envelope.agent_name,
                    "objective": record.envelope.objective,
                    "strategy": record.envelope.strategy or record.child_runtime.request.strategy,
                    "status": record.status,
                    "event": (
                        _public_task_event(event)
                        if (event := self.services.delegations.latest_event(
                            principal_id=self.parent.request.principal_id,
                            task_id=record.envelope.task_id,
                            task_revision=record.envelope.task_revision,
                        )) is not None
                        else None
                    ),
                }
                for record in records
            ]
        }


def _delegated_task_description(request: DelegationRequest) -> str:
    return "\n".join(
        part
        for part in (
            request.agent_name,
            request.objective,
            request.system_prompt,
            " ".join(request.capability_names),
            " ".join(request.acceptance_criteria),
        )
        if part
    )


def _child_system_prompt(system_prompt: str) -> str:
    return (
        f"{system_prompt.strip()}\n\n"
        "Work non-blockingly in the shared workspace. Only claim effects backed by native tool results. "
        "Use only the tools presented "
        "to the current graph node; tool availability can differ between planning, execution, and finalization. "
        "Before a tool call, put one concise user-facing sentence in the assistant content describing what you "
        "are about to do. Keep it factual, action-oriented, and free of private reasoning. Use prospective or "
        "in-progress wording and never claim completion before the authoritative tool result; this sentence is "
        "used as the live task activity summary."
    )


def _public_task_event(event: Any) -> dict[str, Any]:
    payload = dict(event.payload)
    result = payload.get("result")
    error = payload.get("error") if isinstance(payload.get("error"), dict) else None
    return {
        "type": event.event_type,
        **({"result": result} if result is not None else {}),
        **(
            {
                "error": {
                    "code": error.get("code"),
                    "category": error.get("category"),
                    "retryable": error.get("retryable"),
                    "details": error.get("details"),
                }
            }
            if error is not None
            else {}
        ),
        **({"details": payload.get("details")} if payload.get("details") is not None else {}),
        "created_at": event.created_at,
    }
