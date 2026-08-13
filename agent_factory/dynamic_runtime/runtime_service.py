from __future__ import annotations

from dataclasses import dataclass
from contextvars import copy_context
from collections.abc import Callable
from datetime import datetime, timezone
import json
import logging
import threading
from typing import Any, Literal, Protocol

from langchain_core.messages import BaseMessage, ToolMessage
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_factory.dynamic_runtime.conversation_projection import (
    conversation_to_graph_messages,
    graph_messages_to_conversation,
)
from agent_factory.dynamic_runtime.execution_commits import (
    RuntimeCancellationRequested,
    RuntimeExecutionCommitStore,
)
from agent_factory.dynamic_runtime.delegation_store import DelegatedTaskClaim, DelegationStore
from agent_factory.dynamic_runtime.model_service import RuntimeModelResolver, register_runtime_model_handle
from agent_factory.dynamic_runtime.repositories import ConversationStore, RuntimeInstanceStore
from agent_factory.dynamic_runtime.run_control import RuntimeRunControl, RuntimeRunControlRegistry
from agent_factory.dynamic_runtime.services import DynamicRuntimeServiceSet
from agent_factory.dynamic_runtime.snapshot_tool_registry import SnapshotToolRegistryLease
from agent_factory.runtime_kernel.capability_state import bind_capability_snapshot
from agent_factory.runtime_kernel.state import (
    ConversationState,
    ExecutionState,
    RunState,
    RuntimeConfigState,
    RuntimeState,
)
from agent_factory.runtime_kernel.state.checkpoint_projection import runtime_checkpoint_payload
from agent_factory.runtime_protocol import (
    CapabilitySnapshot,
    AttachmentPart,
    ConversationMessage,
    RuntimeErrorEnvelope,
    RuntimeInstance,
    RuntimeModelUsage,
    TaskEnvelope,
    TextPart,
    ToolCallPart,
    ToolCallRecord,
    ToolResultPart,
)
from agent_factory.runtime_protocol.messages import incomplete_tool_call_ids
from agent_factory.tooling.execution_context import (
    runtime_run_control_context,
    tool_output_session_context,
)


RuntimeExecutionStatus = Literal["waiting_approval", "waiting_external", "completed", "failed", "cancelled"]
RuntimeObservationSink = Callable[[RuntimeInstance, Any], None]
logger = logging.getLogger(__name__)


class RuntimeLaunchContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    system_prompt: str
    workspace_root_alias: str = "/workdir"
    allow_external_paths: bool = False
    workspace_mounts: tuple[dict[str, Any], ...] = ()
    attachments: tuple[dict[str, Any], ...] = ()

    @field_validator("system_prompt", "workspace_root_alias")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("runtime launch text must not be empty")
        return text


class RuntimeLaunchContextResolver(Protocol):
    def resolve(
        self,
        *,
        instance: RuntimeInstance,
        messages: list[ConversationMessage],
        capability_snapshot: CapabilitySnapshot,
    ) -> RuntimeLaunchContext:
        ...


@dataclass(frozen=True, slots=True)
class RuntimeExecutionResult:
    runtime_instance: RuntimeInstance
    capability_snapshot: CapabilitySnapshot
    state: RuntimeState
    graph_messages: tuple[BaseMessage, ...]
    conversation_messages: tuple[ConversationMessage, ...]
    status: RuntimeExecutionStatus
    interrupt_payloads: tuple[dict[str, Any], ...] = ()


class DynamicRuntimeService:
    """Authoritative execution entrypoint for main and temporary runtimes."""

    def __init__(
        self,
        *,
        service_set: DynamicRuntimeServiceSet,
        runtime_instances: RuntimeInstanceStore,
        conversations: ConversationStore,
        execution_commits: RuntimeExecutionCommitStore,
        run_controls: RuntimeRunControlRegistry,
        model_resolver: RuntimeModelResolver,
        launch_context_resolver: RuntimeLaunchContextResolver,
        delegations: DelegationStore,
        observation_sink: RuntimeObservationSink | None = None,
    ) -> None:
        self._service_set = service_set
        self._runtime_instances = runtime_instances
        self._conversations = conversations
        self._execution_commits = execution_commits
        self._run_controls = run_controls
        self._model_resolver = model_resolver
        self._launch_context_resolver = launch_context_resolver
        self._delegations = delegations
        self._observation_sink = observation_sink

    def execute(self, runtime_instance_id: str) -> RuntimeExecutionResult:
        return self._run(
            runtime_instance_id=runtime_instance_id,
            resume_payload=None,
            delegation_claim_id=None,
        )

    def execute_delegated(self, claim: DelegatedTaskClaim) -> RuntimeExecutionResult:
        return self._run(
            runtime_instance_id=claim.child_runtime_instance_id,
            resume_payload=None,
            delegation_claim_id=claim.claim_id,
        )

    def resume(self, runtime_instance_id: str, *, resume_payload: dict[str, Any]) -> RuntimeExecutionResult:
        if not isinstance(resume_payload, dict) or not resume_payload:
            raise ValueError("runtime resume requires a non-empty resume_payload")
        return self._run(
            runtime_instance_id=runtime_instance_id,
            resume_payload=resume_payload,
            delegation_claim_id=None,
        )

    def pending_interrupts(self, runtime_instance_id: str) -> tuple[dict[str, Any], ...]:
        instance = self._runtime_instances.get(runtime_instance_id)
        if instance.status not in {"waiting_approval", "waiting_external"}:
            raise RuntimeError("runtime instance is not waiting for an interrupt response")
        graph = self._service_set.graph_for(instance.request.strategy)
        checkpoint = graph.graph_app.get_state(
            {"configurable": {"thread_id": instance.runtime_instance_id}}
        )
        return tuple(_interrupt_payloads(raw={}, checkpoint=checkpoint))

    def current_plan(self, runtime_instance_id: str) -> dict[str, Any] | None:
        instance = self._runtime_instances.get(runtime_instance_id)
        if instance.request.strategy != "plan_and_execute":
            return None
        graph = self._service_set.graph_for(instance.request.strategy)
        checkpoint = graph.graph_app.get_state(
            {"configurable": {"thread_id": instance.runtime_instance_id}}
        )
        values = getattr(checkpoint, "values", None) or {}
        raw_runtime = values.get("runtime") if isinstance(values, dict) else None
        if not isinstance(raw_runtime, dict):
            return None
        state = RuntimeState.model_validate(raw_runtime)
        if state.plan.status == "empty":
            return None
        return state.plan.model_dump(mode="json")

    def _run(
        self,
        *,
        runtime_instance_id: str,
        resume_payload: dict[str, Any] | None,
        delegation_claim_id: str | None,
    ) -> RuntimeExecutionResult:
        instance = self._runtime_instances.get(runtime_instance_id)
        _validate_invocation_status(instance, resuming=resume_payload is not None)
        claimed_instance = self._execution_commits.begin(
            runtime_instance_id,
            resuming=resume_payload is not None,
            delegation_claim_id=delegation_claim_id,
        )
        run_control = self._run_controls.register(claimed_instance.runtime_instance_id)
        tool_registry_lease: SnapshotToolRegistryLease | None = None
        model_registered = False
        runtime_leases_owned_by_worker = False
        runtime_leases_lock = threading.RLock()
        runtime_leases_released = False

        def release_runtime_leases() -> None:
            nonlocal runtime_leases_released
            with runtime_leases_lock:
                if runtime_leases_released:
                    return
                runtime_leases_released = True
            errors: list[BaseException] = []
            if tool_registry_lease is not None:
                try:
                    tool_registry_lease.release()
                except BaseException as exc:
                    errors.append(exc)
            if model_registered:
                try:
                    self._service_set.model_handles.release(claimed_instance.runtime_instance_id)
                except BaseException as exc:
                    errors.append(exc)
            if errors:
                raise RuntimeError(
                    f"runtime lease release failed for {len(errors)} resource(s)"
                ) from errors[0]

        try:
            snapshot = self._runtime_instances.capability_snapshot(claimed_instance.capability_snapshot_id)
            if snapshot.snapshot_id != claimed_instance.request.capability_snapshot_id:
                raise RuntimeError("runtime instance and capability snapshot identities differ")
            tool_registry_lease = self._service_set.snapshot_tool_registries.materialize(
                capability_snapshot=snapshot,
                runtime_instance=claimed_instance,
            )
            canonical_messages, current_user_message = self._runtime_input(claimed_instance)
            launch_context = self._launch_context_resolver.resolve(
                instance=claimed_instance,
                messages=canonical_messages,
                capability_snapshot=snapshot,
            )
            graph = self._service_set.graph_for(claimed_instance.request.strategy)
            resolved_model = self._resolve_frozen_model(claimed_instance)
            register_runtime_model_handle(
                self._service_set.model_handles,
                runtime_instance_id=claimed_instance.runtime_instance_id,
                resolved=resolved_model,
            )
            model_registered = True
            config = {
                "configurable": {
                    "thread_id": claimed_instance.runtime_instance_id,
                }
            }
            if resume_payload is None:
                graph_messages = conversation_to_graph_messages(canonical_messages)
                state = _initial_state(
                    instance=claimed_instance,
                    snapshot=snapshot,
                    current_user_message=current_user_message,
                    launch_context=launch_context,
                )
                graph_input: Any = {
                    "messages": graph_messages,
                    "runtime": runtime_checkpoint_payload(state, mode="json"),
                }
            else:
                checkpoint_values = getattr(graph.graph_app.get_state(config), "values", None) or {}
                resumed_state = RuntimeState.model_validate(checkpoint_values.get("runtime") or {})
                resumed_state.execution.last_activity_at = datetime.now(timezone.utc).isoformat()
                graph_input = Command(
                    update={
                        "runtime": runtime_checkpoint_payload(resumed_state, mode="json"),
                    },
                    resume=_graph_resume_values(resume_payload),
                )
            fallback_raw = (
                graph_input
                if isinstance(graph_input, dict)
                else (getattr(graph.graph_app.get_state(config), "values", None) or {})
            )
            with (
                self._service_set.scoped_tool_registry.bind(tool_registry_lease),
                self._service_set.scoped_context_resources.bind(claimed_instance),
            ):
                runtime_leases_owned_by_worker = True
                raw, graph_detached = _run_graph_with_control(
                    graph_app=graph.graph_app,
                    graph_input=graph_input,
                    config=config,
                    control=run_control,
                    session_id=claimed_instance.request.session_id,
                    fallback_raw=fallback_raw,
                    on_complete=release_runtime_leases,
                    on_observation=(
                        (lambda chunk: self._observation_sink(claimed_instance, chunk))
                        if self._observation_sink is not None
                        else None
                    ),
                )
            checkpoint = graph.graph_app.get_state(config)
            authoritative = getattr(checkpoint, "values", None) or raw
            if not isinstance(authoritative, dict):
                raise RuntimeError("fixed runtime graph returned an invalid checkpoint projection")
            state = RuntimeState.model_validate(authoritative.get("runtime") or {})
            if graph_detached or run_control.drain_requested:
                state.execution.interrupted = True
                state.execution.finished = True
                state.execution.finish_status = "cancelled"
                state.execution.last_error_location = "runtime.cancel"
            graph_messages = list(authoritative.get("messages") or [])
            interrupts = _interrupt_payloads(raw=raw, checkpoint=checkpoint)
            status = _execution_status(state=state, graph_messages=graph_messages, interrupts=interrupts)
            projection_messages = list(graph_messages)
            if status in {"completed", "failed", "cancelled"}:
                projection_messages = _close_terminal_tool_calls(projection_messages, status=status)
            projected_for_records = graph_messages_to_conversation(
                graph_messages=projection_messages,
                current_user_message_id=current_user_message.message_id,
                session_id=claimed_instance.request.session_id,
                turn_id=claimed_instance.request.turn_id,
                runtime_instance_id=claimed_instance.runtime_instance_id,
                request_id=claimed_instance.request.request_id,
                task_revision=claimed_instance.request.task_revision,
                capability_snapshot=snapshot,
            )
            projected_messages = (
                []
                if claimed_instance.request.runtime_role == "temporary"
                or status in {"waiting_approval", "waiting_external"}
                else projected_for_records
            )
            projected_tool_calls = _tool_call_records(
                projected_for_records,
                instance=claimed_instance,
                waiting_status=status,
                observations=state.observability.events,
            )
            delivery_error = _delegated_delivery_error(
                instance=claimed_instance,
                status=status,
                graph_messages=projection_messages,
                tool_calls=projected_tool_calls,
            )
            if delivery_error is not None:
                status = "failed"
                state.execution.finished = True
                state.execution.finish_status = "failed"
                state.execution.last_error = delivery_error
                state.execution.last_error_location = "delegation.delivery"
            error = _terminal_error(claimed_instance, status=status, state=state)
            try:
                committed_instance = self._execution_commits.commit(
                    claimed_instance=claimed_instance,
                    status=status,
                    event_payload=_event_payload(
                        claimed_instance,
                        state=state,
                        status=status,
                        interrupts=interrupts,
                        error=error,
                        graph_messages=projection_messages,
                        conversation_messages=projected_messages,
                        tool_calls=projected_tool_calls,
                    ),
                    messages=projected_messages,
                    tool_calls=projected_tool_calls,
                    model_usage=_model_usage_records(claimed_instance, state.observability.events),
                    error=error,
                )
            except RuntimeCancellationRequested:
                status = "cancelled"
                latest = self._runtime_instances.get(claimed_instance.runtime_instance_id)
                state.execution.interrupted = True
                state.execution.finished = True
                state.execution.finish_status = "cancelled"
                state.execution.last_error_location = "runtime.cancel"
                projection_messages = _close_terminal_tool_calls(graph_messages, status=status)
                projected_for_records = graph_messages_to_conversation(
                    graph_messages=projection_messages,
                    current_user_message_id=current_user_message.message_id,
                    session_id=claimed_instance.request.session_id,
                    turn_id=claimed_instance.request.turn_id,
                    runtime_instance_id=claimed_instance.runtime_instance_id,
                    request_id=claimed_instance.request.request_id,
                    task_revision=claimed_instance.request.task_revision,
                    capability_snapshot=snapshot,
                )
                projected_messages = (
                    []
                    if claimed_instance.request.runtime_role == "temporary"
                    else projected_for_records
                )
                error = _terminal_error(latest, status=status, state=state)
                committed_instance = self._execution_commits.commit(
                    claimed_instance=claimed_instance,
                    status=status,
                    event_payload=_event_payload(
                        latest,
                        state=state,
                        status=status,
                        interrupts=[],
                        error=error,
                        graph_messages=projection_messages,
                        conversation_messages=projected_messages,
                        tool_calls=_tool_call_records(
                            projected_for_records,
                            instance=claimed_instance,
                            waiting_status=status,
                            observations=state.observability.events,
                        ),
                    ),
                    messages=projected_messages,
                    tool_calls=_tool_call_records(
                        projected_for_records,
                        instance=claimed_instance,
                        waiting_status=status,
                        observations=state.observability.events,
                    ),
                    model_usage=_model_usage_records(claimed_instance, state.observability.events),
                    error=error,
                )
            return RuntimeExecutionResult(
                runtime_instance=committed_instance,
                capability_snapshot=snapshot,
                state=state,
                graph_messages=tuple(projection_messages),
                conversation_messages=tuple(projected_messages),
                status=status,
                interrupt_payloads=tuple(interrupts),
            )
        except Exception as exc:
            logger.exception(
                "Dynamic runtime execution failed: runtime_instance_id=%s request_id=%s turn_id=%s",
                claimed_instance.runtime_instance_id,
                claimed_instance.request.request_id,
                claimed_instance.request.turn_id,
            )
            error = _exception_error(claimed_instance, exc)
            try:
                self._execution_commits.fail_claimed(claimed_instance, error)
            except Exception as persistence_error:
                raise RuntimeError("runtime execution failed and its terminal commit was rejected") from persistence_error
            raise
        finally:
            if not runtime_leases_owned_by_worker:
                release_runtime_leases()
            self._run_controls.release(claimed_instance.runtime_instance_id, run_control)

    def _runtime_input(
        self,
        instance: RuntimeInstance,
    ) -> tuple[list[ConversationMessage], ConversationMessage]:
        if instance.request.runtime_role == "main":
            messages = self._conversations.messages_through_task_revision(
                session_id=instance.request.session_id,
                task_revision=instance.request.task_revision,
            )
            return messages, _current_user_message(instance, messages)
        record = self._delegations.for_runtime(instance.runtime_instance_id)
        if record.child_runtime.request != instance.request:
            raise RuntimeError("delegated task runtime request changed after task creation")
        message = _delegated_task_message(instance, record.envelope)
        return [message], message

    def _resolve_frozen_model(self, instance: RuntimeInstance):
        frozen = instance.request.policy_snapshot.model
        resolved = self._model_resolver.resolve_chat_model(
            operation=frozen.operation,
            profile_id=frozen.profile_id,
            expected_profile_revision=frozen.profile_revision,
            expected_credential_revision=frozen.credential_revision,
            reasoning_intensity=instance.request.policy_snapshot.reasoning_intensity,
        )
        if resolved.snapshot != frozen:
            raise RuntimeError("resolved model does not match the runtime policy snapshot")
        return resolved


def _initial_state(
    *,
    instance: RuntimeInstance,
    snapshot: CapabilitySnapshot,
    current_user_message: ConversationMessage,
    launch_context: RuntimeLaunchContext,
) -> RuntimeState:
    state = RuntimeState(
        run=RunState(
            run_id=instance.runtime_instance_id,
            runtime_instance_id=instance.runtime_instance_id,
            session_id=instance.request.session_id,
            workspace_id=instance.request.workspace_id,
            strategy=instance.request.strategy,
        ),
        runtime_config=RuntimeConfigState(
            system_prompt=launch_context.system_prompt,
            attachments=[dict(item) for item in launch_context.attachments],
            workspace_root_alias=launch_context.workspace_root_alias,
            allow_external_paths=launch_context.allow_external_paths,
            workspace_mounts=[dict(item) for item in launch_context.workspace_mounts],
        ),
        conversation=ConversationState(
            current_user_input=_message_text(current_user_message),
            current_user_input_id=current_user_message.message_id,
        ),
        execution=ExecutionState(
            max_retries=instance.request.policy_snapshot.max_model_attempts - 1,
            timeout_seconds=instance.request.policy_snapshot.request_timeout_seconds,
            last_activity_at=datetime.now(timezone.utc).isoformat(),
        ),
    )
    return bind_capability_snapshot(
        state,
        snapshot,
        runtime_instance_id=instance.runtime_instance_id,
    )


def _current_user_message(
    instance: RuntimeInstance,
    messages: list[ConversationMessage],
) -> ConversationMessage:
    candidates = [
        message
        for message in messages
        if message.turn_id == instance.request.turn_id
        and message.role == "user"
        and message.status != "cancelled"
    ]
    if len(candidates) != 1:
        raise LookupError(
            "runtime turn requires exactly one active user message: "
            f"turn_id={instance.request.turn_id}, count={len(candidates)}"
        )
    return candidates[0]


def _delegated_task_message(
    instance: RuntimeInstance,
    envelope: TaskEnvelope,
) -> ConversationMessage:
    if (
        envelope.task_id != instance.request.task_id
        or envelope.task_revision != instance.request.task_revision
        or envelope.parent_runtime_instance_id != instance.request.parent_runtime_instance_id
        or envelope.capability_snapshot_id != instance.capability_snapshot_id
    ):
        raise RuntimeError("delegated task envelope differs from the runtime request")
    instruction = json.dumps(
        {
            "objective": envelope.objective,
            "acceptance_criteria": list(envelope.acceptance_criteria),
            "context_facts": list(envelope.context_facts),
            "allowed_write_roots": list(envelope.allowed_write_roots),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return ConversationMessage(
        message_id=f"delegated-task:{envelope.task_id}:{envelope.task_revision}",
        session_id=instance.request.session_id,
        turn_id=instance.request.turn_id,
        role="user",
        status="committed",
        parts=(
            TextPart(text=instruction),
            *(AttachmentPart(attachment=item) for item in envelope.input_artifacts),
        ),
        created_at=envelope.created_at,
        committed_at=envelope.created_at,
    )


def _message_text(message: ConversationMessage) -> str:
    chunks = [str(getattr(part, "text", "") or "").strip() for part in message.parts]
    text = "\n".join(item for item in chunks if item)
    if not text:
        raise ValueError("runtime user message contains no text instruction")
    return text


def _validate_invocation_status(instance: RuntimeInstance, *, resuming: bool) -> None:
    expected = {"waiting_approval", "waiting_external"} if resuming else {"queued"}
    if instance.status not in expected:
        action = "resume" if resuming else "execute"
        raise RuntimeError(
            f"cannot {action} runtime instance in status {instance.status!r}; "
            f"expected one of {sorted(expected)}"
        )


def _interrupt_payloads(*, raw: Any, checkpoint: Any) -> list[dict[str, Any]]:
    values: list[Any] = []
    if isinstance(raw, dict):
        values.extend(list(raw.get("__interrupt__") or []))
    for task in list(getattr(checkpoint, "tasks", ()) or ()):
        values.extend(list(getattr(task, "interrupts", ()) or ()))
    payloads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        value = getattr(item, "value", item)
        payload = dict(value) if isinstance(value, dict) else {"value": value}
        interrupt_id = str(getattr(item, "id", "") or "").strip()
        if interrupt_id:
            payload["interrupt_id"] = interrupt_id
        marker = repr(sorted(payload.items(), key=lambda pair: str(pair[0])))
        if marker not in seen:
            seen.add(marker)
            payloads.append(payload)
    return payloads


def _graph_resume_values(payload: dict[str, Any]) -> dict[str, Any]:
    interrupt_id = str(payload.get("interrupt_id") or "").strip()
    decision = str(payload.get("decision") or "").strip()
    response = str(payload.get("response") or "").strip()
    if not interrupt_id:
        raise ValueError("runtime resume payload requires an interrupt identity")
    if decision == "approve":
        value: Any = {"action": "approve"}
    elif decision == "deny":
        value = {"action": "deny"}
    elif decision == "trust_tool":
        value = {"action": "trust_tool"}
    elif decision == "revise":
        if not response:
            raise ValueError("runtime revision requires guidance")
        value = {"action": "revise", "revision_guidance": response}
    elif decision == "answer":
        if not response:
            raise ValueError("runtime answer requires a response")
        value = response
    else:
        raise ValueError(f"unsupported runtime interrupt decision: {decision!r}")
    return {interrupt_id: value}


def _execution_status(
    *,
    state: RuntimeState,
    graph_messages: list[BaseMessage],
    interrupts: list[dict[str, Any]],
) -> RuntimeExecutionStatus:
    if state.execution.finish_status in {"cancelled", "interrupted"}:
        return "cancelled"
    if interrupts:
        if any(str(item.get("kind") or item.get("type") or "").lower().find("approval") >= 0 for item in interrupts):
            return "waiting_approval"
        return "waiting_external"
    missing = incomplete_tool_call_ids(graph_messages)
    if missing:
        state.execution.finished = True
        state.execution.finish_status = "failed"
        state.execution.last_error = "Runtime graph ended with incomplete tool calls: " + ", ".join(missing)
        state.execution.last_error_location = "runtime.finalize"
        return "failed"
    if state.execution.finish_status == "completed" and not state.execution.last_error:
        return "completed"
    if not state.execution.finished:
        state.execution.finished = True
        state.execution.finish_status = "failed"
        state.execution.last_error = state.execution.last_error or "Runtime graph stopped before a terminal node."
        state.execution.last_error_location = state.execution.last_error_location or "runtime.finalize"
    return "failed"


def _delegated_delivery_error(
    *,
    instance: RuntimeInstance,
    status: RuntimeExecutionStatus,
    graph_messages: list[BaseMessage],
    tool_calls: tuple[ToolCallRecord, ...],
) -> str | None:
    if instance.request.runtime_role != "temporary" or status != "completed":
        return None
    final_content = _final_graph_message_content(graph_messages)
    rendered = json.dumps(final_content, ensure_ascii=False) if not isinstance(final_content, str) else final_content
    if "DSML" in rendered and "tool_calls" in rendered:
        return "Temporary agent returned serialized tool markup instead of a native tool call."
    required_tools = tuple(instance.request.route_decision.capability_requirements)
    if required_tools and not tool_calls:
        return "Temporary agent completed without executing any of its required tools."
    unresolved = tuple(
        record.model_alias
        for record in tool_calls
        if record.status in {"proposed", "waiting_approval", "running"}
    )
    if unresolved:
        return "Temporary agent has unresolved tool calls: " + ", ".join(unresolved)
    return None


def _close_terminal_tool_calls(
    graph_messages: list[BaseMessage],
    *,
    status: RuntimeExecutionStatus,
) -> list[BaseMessage]:
    missing = incomplete_tool_call_ids(graph_messages)
    if not missing:
        return graph_messages
    result_status = "cancelled" if status == "cancelled" else "failed"
    error_code = "runtime_cancelled" if status == "cancelled" else "runtime_terminal_before_tool_result"
    closed = list(graph_messages)
    for tool_call_id in missing:
        closed.append(
            ToolMessage(
                id=f"terminal:{tool_call_id}",
                tool_call_id=tool_call_id,
                content=json.dumps(
                    {"status": result_status, "error_code": error_code},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        )
    return closed


def _tool_call_records(
    messages: list[ConversationMessage],
    *,
    instance: RuntimeInstance,
    waiting_status: RuntimeExecutionStatus,
    observations: list[dict[str, Any]],
) -> tuple[ToolCallRecord, ...]:
    if instance.attempt_id is None:
        raise RuntimeError("claimed runtime instance has no attempt identity")
    records: dict[str, dict[str, Any]] = {}
    event_times = _tool_event_times(observations)
    for message in messages:
        for part in message.parts:
            if isinstance(part, ToolCallPart):
                initial_status = "waiting_approval" if waiting_status == "waiting_approval" else "proposed"
                observed = event_times.get(part.tool_call_id, {})
                records[part.tool_call_id] = {
                    "tool_call_id": part.tool_call_id,
                    "runtime_instance_id": instance.runtime_instance_id,
                    "request_id": instance.request.request_id,
                    "turn_id": instance.request.turn_id,
                    "attempt_id": instance.attempt_id,
                    "capability_id": part.capability_id,
                    "capability_revision": part.capability_revision,
                    "model_alias": part.model_alias,
                    "arguments": dict(part.arguments),
                    "status": initial_status,
                    "created_at": observed.get("started_at") or message.created_at,
                    "updated_at": observed.get("started_at") or message.created_at,
                }
            elif isinstance(part, ToolResultPart):
                record = records.get(part.tool_call_id)
                if record is None:
                    raise RuntimeError(f"tool result has no projected tool call: {part.tool_call_id}")
                record["status"] = part.status
                observed = event_times.get(part.tool_call_id, {})
                record["updated_at"] = observed.get("completed_at") or message.created_at
                if part.status == "completed":
                    record["result"] = dict(part.output or {})
                else:
                    record["error_code"] = part.error_code
    return tuple(ToolCallRecord.model_validate(record) for record in records.values())


def _tool_event_times(observations: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    event_times: dict[str, dict[str, str]] = {}
    for observation in observations:
        event_type = str(observation.get("event_type") or "")
        if event_type not in {"tool_proposed", "tool_started", "tool_completed", "tool_failed"}:
            continue
        payload = observation.get("payload")
        if not isinstance(payload, dict):
            continue
        tool_call_id = str(payload.get("tool_call_id") or "").strip()
        created_at = str(observation.get("created_at") or "").strip()
        if not tool_call_id or not created_at:
            continue
        times = event_times.setdefault(tool_call_id, {})
        if event_type in {"tool_proposed", "tool_started"}:
            times.setdefault("started_at", created_at)
        else:
            times["completed_at"] = created_at
    return event_times


def _model_usage_records(
    instance: RuntimeInstance,
    observations: list[dict[str, Any]],
) -> tuple[RuntimeModelUsage, ...]:
    if instance.attempt_id is None:
        raise RuntimeError("runtime model usage requires a claimed attempt identity")
    request = instance.request
    frozen_model = request.policy_snapshot.model
    records: list[RuntimeModelUsage] = []
    for observation in observations:
        if str(observation.get("event_type") or "") != "model_usage_completed":
            continue
        payload = observation.get("payload")
        if not isinstance(payload, dict):
            raise RuntimeError("model usage observation payload must be an object")
        if str(payload.get("version") or "") != "runtime_model_usage_observation.v1":
            raise RuntimeError("model usage observation uses an unsupported schema")
        observed_model = (
            str(payload.get("model_operation") or ""),
            str(payload.get("model_profile_id") or ""),
            int(payload.get("model_profile_revision") or 0),
            str(payload.get("provider") or ""),
            str(payload.get("model_name") or ""),
        )
        frozen_identity = (
            frozen_model.operation,
            frozen_model.profile_id,
            frozen_model.profile_revision,
            frozen_model.provider,
            frozen_model.model_name,
        )
        if observed_model != frozen_identity:
            raise RuntimeError("model usage observation differs from the frozen model selection")
        records.append(
            RuntimeModelUsage(
                observation_event_id=str(observation.get("event_id") or ""),
                principal_id=request.principal_id,
                request_id=request.request_id,
                runtime_instance_id=instance.runtime_instance_id,
                attempt_id=instance.attempt_id,
                session_id=request.session_id,
                turn_id=request.turn_id,
                workspace_id=request.workspace_id,
                task_revision=request.task_revision,
                runtime_role=request.runtime_role,
                strategy=request.strategy,
                node_id=str(payload.get("node_id") or ""),
                model_operation=frozen_model.operation,
                model_profile_id=frozen_model.profile_id,
                model_profile_revision=frozen_model.profile_revision,
                provider=frozen_model.provider,
                model_name=frozen_model.model_name,
                input_tokens=int(payload.get("input_tokens") or 0),
                output_tokens=int(payload.get("output_tokens") or 0),
                total_tokens=int(payload.get("total_tokens") or 0),
                reasoning_tokens=int(payload.get("reasoning_tokens") or 0),
                cache_read_tokens=int(payload.get("cache_read_tokens") or 0),
                cache_write_tokens=int(payload.get("cache_write_tokens") or 0),
                created_at=str(observation.get("created_at") or ""),
            )
        )
    return tuple(records)


def _event_payload(
    instance: RuntimeInstance,
    *,
    state: RuntimeState,
    status: RuntimeExecutionStatus,
    interrupts: list[dict[str, Any]],
    error: RuntimeErrorEnvelope | None,
    graph_messages: list[BaseMessage],
    conversation_messages: list[ConversationMessage],
    tool_calls: tuple[ToolCallRecord, ...],
) -> dict[str, Any]:
    if status in {"waiting_approval", "waiting_external"}:
        source = (
            {
                "task_id": instance.request.task_id,
                "parent_runtime_instance_id": instance.request.parent_runtime_instance_id,
                "runtime_role": instance.request.runtime_role,
            }
            if instance.request.runtime_role == "temporary"
            else {"runtime_role": instance.request.runtime_role}
        )
        return {
            "kind": f"runtime_{status}",
            "status": status,
            "details": {
                "interrupts": _json_safe(interrupts),
                "source": source,
            },
        }
    if status == "completed":
        assistant_message = next(
            (message for message in reversed(conversation_messages) if message.role == "assistant"),
            None,
        )
        final_content = _final_graph_message_content(graph_messages)
        result = (
            {
                "summary": final_content,
                "verified": True,
                "tool_evidence": [
                    {
                        "tool": record.model_alias,
                        "status": record.status,
                        "result": record.result,
                    }
                    for record in tool_calls
                ],
            }
            if instance.request.runtime_role == "temporary"
            else final_content
        )
        return {
            "kind": "runtime_completed",
            "status": "completed",
            "result": result,
            "message": (
                {
                    "message_id": assistant_message.message_id,
                    "parts": [part.model_dump(mode="json") for part in assistant_message.parts],
                    "created_at": assistant_message.created_at,
                }
                if assistant_message is not None
                else None
            ),
            "context_window": _latest_context_window(state),
        }
    if error is None:
        raise RuntimeError(f"terminal runtime status requires an error envelope: {status}")
    return {"kind": status, "error": error.model_dump(mode="json")}


def _latest_context_window(state: RuntimeState) -> dict[str, Any] | None:
    for raw_event in reversed(state.observability.events):
        if not isinstance(raw_event, dict) or raw_event.get("event_type") != "context_window_updated":
            continue
        payload = raw_event.get("payload")
        if not isinstance(payload, dict):
            continue
        return {
            key: _json_safe(value)
            for key, value in payload.items()
            if key != "event_type"
        }
    return None


def _final_graph_message_content(messages: list[BaseMessage]) -> Any:
    for message in reversed(messages):
        if getattr(message, "type", "") in {"ai", "assistant"}:
            return _json_safe(getattr(message, "content", ""))
    raise RuntimeError("completed runtime has no assistant result message")


def _terminal_error(
    instance: RuntimeInstance,
    *,
    status: RuntimeExecutionStatus,
    state: RuntimeState,
) -> RuntimeErrorEnvelope | None:
    if status not in {"failed", "cancelled"}:
        return None
    cancelled = status == "cancelled"
    return RuntimeErrorEnvelope(
        code="runtime_cancelled" if cancelled else "runtime_execution_failed",
        category="cancelled" if cancelled else "internal",
        terminal_status=status,
        retryable=False,
        user_message_key="runtime.cancelled" if cancelled else "runtime.error.execution_failed",
        request_id=instance.request.request_id,
        runtime_instance_id=instance.runtime_instance_id,
        operation=instance.request.policy_snapshot.model.operation,
        details={
            "error_location": str(state.execution.last_error_location or "runtime.finalize"),
            "message": str(state.execution.last_error or "runtime execution failed"),
        },
    )


def _exception_error(instance: RuntimeInstance, exc: Exception) -> RuntimeErrorEnvelope:
    name = type(exc).__name__
    lowered = name.lower()
    if "timeout" in lowered:
        category = "timeout"
        code = "runtime_timeout"
        retryable = True
    elif "model" in lowered or "provider" in lowered:
        category = "provider"
        code = "runtime_model_unavailable"
        retryable = True
    elif isinstance(exc, (ValueError, LookupError)):
        category = "validation"
        code = "runtime_validation_failed"
        retryable = False
    else:
        category = "internal"
        code = "runtime_internal_error"
        retryable = False
    return RuntimeErrorEnvelope(
        code=code,
        category=category,
        terminal_status="failed",
        retryable=retryable,
        user_message_key=f"runtime.error.{code}",
        request_id=instance.request.request_id,
        runtime_instance_id=instance.runtime_instance_id,
        operation=instance.request.policy_snapshot.model.operation,
        details={
            "exception_type": name,
            "message": str(exc).strip() or name,
        },
    )


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _run_graph_with_control(
    *,
    graph_app: Any,
    graph_input: Any,
    config: dict[str, Any],
    control: RuntimeRunControl,
    session_id: str,
    fallback_raw: dict[str, Any],
    on_complete: Callable[[], None],
    on_observation: Callable[[Any], None] | None,
) -> tuple[dict[str, Any], bool]:
    if control.drain_requested:
        on_complete()
        return fallback_raw, True
    completed = threading.Event()
    outcome: dict[str, Any] = {"raw": fallback_raw}
    context = copy_context()

    def run() -> None:
        try:
            with (
                tool_output_session_context(session_id),
                runtime_run_control_context(control),
            ):
                for mode, chunk in graph_app.stream(
                    graph_input,
                    config=config,
                    stream_mode=["values", "custom"],
                    durability="sync",
                ):
                    if mode == "values" and isinstance(chunk, dict):
                        outcome["raw"] = chunk
                    elif mode == "custom" and on_observation is not None:
                        on_observation(chunk)
        except BaseException as exc:
            outcome["error"] = exc
        finally:
            try:
                on_complete()
            except BaseException as exc:
                outcome.setdefault("error", exc)
            finally:
                completed.set()

    worker = threading.Thread(
        target=lambda: context.run(run),
        name="dynamic-runtime-graph",
        daemon=True,
    )
    try:
        worker.start()
    except BaseException:
        on_complete()
        raise
    while not completed.wait(timeout=0.05):
        if control.drain_requested:
            return dict(outcome["raw"]), True
    error = outcome.get("error")
    if error is not None:
        raise error
    return dict(outcome["raw"]), False
