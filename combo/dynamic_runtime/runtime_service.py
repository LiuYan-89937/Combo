from __future__ import annotations

from dataclasses import dataclass
from contextvars import copy_context
from collections.abc import Callable
from datetime import datetime, timezone
import json
import logging
import threading
from time import perf_counter
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.types import Command

from combo.dynamic_runtime.conversation_context import ConversationContextService
from combo.dynamic_runtime.context_snapshot_store import (
    ConversationContextSnapshotStore,
)
from combo.dynamic_runtime.execution_commits import (
    RuntimeCancellationRequested,
    RuntimeExecutionCommitStore,
)
from combo.dynamic_runtime.launch_context import RuntimeLaunchContext, RuntimeLaunchContextResolver
from combo.dynamic_runtime.delegation_store import DelegatedTaskClaim, DelegationStore
from combo.dynamic_runtime.model_service import RuntimeModelResolver, register_runtime_model_handle
from combo.dynamic_runtime.policy_repositories import UserRuntimePolicyStore
from combo.dynamic_runtime.repositories import ConversationStore, RuntimeInstanceStore
from combo.dynamic_runtime.runtime_results import (
    RuntimeExecutionStatus,
    RuntimeMessageProjection,
    close_terminal_tool_calls,
    drain_runtime_observations,
    final_graph_message_content,
    interrupt_payloads,
    project_model_usage_records,
    project_runtime_messages,
    runtime_event_payload,
)
from combo.dynamic_runtime.runtime_inspection import RuntimeInspectionService
from combo.dynamic_runtime.run_control import RuntimeRunControl, RuntimeRunControlRegistry
from combo.dynamic_runtime.services import DynamicRuntimeServiceSet
from combo.dynamic_runtime.snapshot_tool_registry import SnapshotToolRegistryLease
from combo.runtime_kernel.capability_state import bind_capability_snapshot
from combo.runtime_kernel.persistence import delete_checkpoint_thread
from combo.runtime_kernel.state import (
    ContextState,
    ConversationState,
    ExecutionState,
    RunState,
    RuntimeConfigState,
    RuntimeState,
)
from combo.runtime_kernel.state.checkpoint_projection import runtime_checkpoint_payload
from combo.runtime_protocol import (
    CapabilitySnapshot,
    AttachmentPart,
    ConversationMessage,
    RuntimeErrorEnvelope,
    RuntimeInstance,
    TaskEnvelope,
    TextPart,
    ToolCallRecord,
)
from combo.runtime_protocol.messages import (
    incomplete_tool_call_ids,
)
from combo.context_system.history import release_context_history
from combo.runtime_protocol.interruption import RuntimeModelGenerationInterrupted, RuntimeToolExecutionCancelled
from combo.tooling.execution_context import (
    runtime_run_control_context,
    tool_output_session_context,
)


RuntimeObservationSink = Callable[[RuntimeInstance, Any], None]
logger = logging.getLogger(__name__)


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
        runtime_policies: UserRuntimePolicyStore,
        conversations: ConversationStore,
        context_snapshots: ConversationContextSnapshotStore,
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
        self._inspection = RuntimeInspectionService(
            service_set=service_set,
            runtime_instances=runtime_instances,
            model_resolver=model_resolver,
        )
        self._conversation_context = ConversationContextService(
            conversations=conversations,
            context_snapshots=context_snapshots,
            runtime_instances=runtime_instances,
            runtime_policies=runtime_policies,
            model_resolver=model_resolver,
            context_system=service_set.services.context_system,
            inspection=self._inspection,
        )

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
        return self._inspection.pending_interrupts(runtime_instance_id)

    def current_observations(self, runtime_instance_id: str) -> list[dict[str, Any]]:
        return self._inspection.current_observations(runtime_instance_id)

    def current_plan(self, runtime_instance_id: str) -> dict[str, Any] | None:
        return self._inspection.current_plan(runtime_instance_id)

    def current_context_window(self, runtime_instance_id: str) -> dict[str, Any] | None:
        return self._inspection.current_context_window(runtime_instance_id)

    def compress_main_context(
        self,
        *,
        session_id: str,
        principal_id: str,
    ) -> dict[str, Any]:
        return self._conversation_context.compress_main_context(
            session_id=session_id,
            principal_id=principal_id,
        )

    def _run(
        self,
        *,
        runtime_instance_id: str,
        resume_payload: dict[str, Any] | None,
        delegation_claim_id: str | None,
    ) -> RuntimeExecutionResult:
        instance = self._runtime_instances.get(runtime_instance_id)
        _validate_invocation_status(instance, resuming=resume_payload is not None)
        # Register ownership before publishing running; cancellation can then
        # distinguish an active execution from an abandoned database record.
        run_control = self._run_controls.register(runtime_instance_id)
        try:
            claimed_instance = self._execution_commits.begin(
                runtime_instance_id,
                resuming=resume_payload is not None,
                delegation_claim_id=delegation_claim_id,
            )
        except BaseException:
            self._run_controls.release(runtime_instance_id, run_control)
            raise
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
            materialization_started_at = perf_counter()
            tool_registry_lease = self._service_set.snapshot_tool_registries.materialize(
                capability_snapshot=snapshot,
                runtime_instance=claimed_instance,
            )
            logger.info(
                "Runtime tool surface materialized: runtime_instance_id=%s tool_count=%d elapsed_ms=%.1f",
                claimed_instance.runtime_instance_id,
                len(snapshot.tool_ids),
                (perf_counter() - materialization_started_at) * 1000,
            )
            canonical_messages, current_user_message = self._runtime_input(claimed_instance)
            graph = self._service_set.graph_for(claimed_instance.request.strategy)
            resolved_model = self._model_resolver.resolve_for_instance(claimed_instance)
            compression_model = self._model_resolver.resolve_compression_for_instance(
                claimed_instance,
                fallback=resolved_model,
            )
            register_runtime_model_handle(
                self._service_set.model_handles,
                runtime_instance_id=claimed_instance.runtime_instance_id,
                resolved=resolved_model,
                compression_resolved=compression_model,
            )
            model_registered = True
            config = {
                "configurable": {
                    "thread_id": claimed_instance.runtime_instance_id,
                }
            }
            superseded_checkpoint_thread_id: str | None = None
            if resume_payload is None:
                launch_context = self._launch_context_resolver.resolve(
                    instance=claimed_instance,
                    messages=canonical_messages,
                    capability_snapshot=snapshot,
                )
                graph_messages = self._conversation_context.session_messages(
                    session_id=claimed_instance.request.session_id,
                    through_task_revision=claimed_instance.request.task_revision,
                    canonical_messages=canonical_messages,
                    runtime_role=claimed_instance.request.runtime_role,
                )
                continuation = self._delegated_continuation_messages(
                    instance=claimed_instance,
                    graph=graph,
                    current_messages=graph_messages,
                )
                if continuation is not None:
                    graph_messages, superseded_checkpoint_thread_id = continuation
                state = _initial_state(
                    instance=claimed_instance,
                    snapshot=snapshot,
                    current_user_message=current_user_message,
                    launch_context=launch_context,
                    inherited_context_window=self._conversation_context.inherited_context_window(claimed_instance),
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
            observation_sink = self._observation_sink
            with (
                self._service_set.scoped_tool_registry.bind(tool_registry_lease),
                self._service_set.scoped_context_resources.bind(claimed_instance),
            ):
                runtime_leases_owned_by_worker = True
                raw = _run_graph_with_control(
                    graph_app=graph.graph_app,
                    graph_input=graph_input,
                    config=config,
                    control=run_control,
                    session_id=claimed_instance.request.session_id,
                    fallback_raw=fallback_raw,
                    on_complete=release_runtime_leases,
                    on_observation=(
                        (lambda chunk: observation_sink(claimed_instance, chunk))
                        if observation_sink is not None
                        else None
                    ),
                )
            checkpoint = graph.graph_app.get_state(config)
            authoritative = getattr(checkpoint, "values", None) or raw
            if not isinstance(authoritative, dict):
                raise RuntimeError("fixed runtime graph returned an invalid checkpoint projection")
            state = RuntimeState.model_validate(authoritative.get("runtime") or {})
            state.observability.events = drain_runtime_observations(
                self._service_set.services.observability_manager,
                state=state,
            )
            if run_control.drain_requested:
                state.execution.interrupted = True
                state.execution.finished = True
                state.execution.finish_status = "cancelled"
                state.execution.last_error_location = "runtime.cancel"
            graph_messages = list(authoritative.get("messages") or [])
            run_control.acknowledge_checkpointed_inputs(graph_messages)
            interrupts = interrupt_payloads(raw=raw, checkpoint=checkpoint)
            status = _execution_status(state=state, graph_messages=graph_messages, interrupts=interrupts)
            projection = project_runtime_messages(
                instance=claimed_instance,
                snapshot=snapshot,
                state=state,
                status=status,
                graph_messages=graph_messages,
                current_user_message_id=current_user_message.message_id,
                graph_store=self._service_set.services.graph_store,
            )
            delivery_error = _delegated_delivery_error(
                instance=claimed_instance,
                status=status,
                graph_messages=projection.transcript_graph_messages,
                tool_calls=projection.tool_calls,
            )
            if delivery_error is not None:
                status = "failed"
                state.execution.finished = True
                state.execution.finish_status = "failed"
                state.execution.last_error = delivery_error
                state.execution.last_error_location = "delegation.delivery"
                projection = project_runtime_messages(
                    instance=claimed_instance,
                    snapshot=snapshot,
                    state=state,
                    status=status,
                    graph_messages=graph_messages,
                    current_user_message_id=current_user_message.message_id,
                    graph_store=self._service_set.services.graph_store,
                )
            error = _terminal_error(claimed_instance, status=status, state=state)
            try:
                committed_instance = self._commit_projection(
                    claimed_instance=claimed_instance,
                    event_instance=claimed_instance,
                    state=state,
                    status=status,
                    interrupts=interrupts,
                    projection=projection,
                    error=error,
                )
            except RuntimeCancellationRequested:
                status = "cancelled"
                latest = self._runtime_instances.get(claimed_instance.runtime_instance_id)
                state.execution.interrupted = True
                state.execution.finished = True
                state.execution.finish_status = "cancelled"
                state.execution.last_error_location = "runtime.cancel"
                interrupts = []
                projection = project_runtime_messages(
                    instance=claimed_instance,
                    snapshot=snapshot,
                    state=state,
                    status=status,
                    graph_messages=graph_messages,
                    current_user_message_id=current_user_message.message_id,
                    graph_store=self._service_set.services.graph_store,
                )
                error = _terminal_error(latest, status=status, state=state)
                committed_instance = self._commit_projection(
                    claimed_instance=claimed_instance,
                    event_instance=latest,
                    state=state,
                    status=status,
                    interrupts=interrupts,
                    projection=projection,
                    error=error,
                )
            if status in {"completed", "failed", "cancelled"}:
                release_context_history(store=self._service_set.services.graph_store, state=state)
            if superseded_checkpoint_thread_id is not None:
                self._delete_superseded_checkpoint(superseded_checkpoint_thread_id)
            return RuntimeExecutionResult(
                runtime_instance=committed_instance,
                capability_snapshot=snapshot,
                state=state,
                graph_messages=tuple(projection.context_messages),
                conversation_messages=tuple(projection.conversation_messages),
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
            try:
                if not runtime_leases_owned_by_worker:
                    release_runtime_leases()
            finally:
                self._run_controls.release(claimed_instance.runtime_instance_id, run_control)

    def _commit_projection(
        self,
        *,
        claimed_instance: RuntimeInstance,
        event_instance: RuntimeInstance,
        state: RuntimeState,
        status: RuntimeExecutionStatus,
        interrupts: list[dict[str, Any]],
        projection: RuntimeMessageProjection,
        error: RuntimeErrorEnvelope | None,
    ) -> RuntimeInstance:
        return self._execution_commits.commit(
            claimed_instance=claimed_instance,
            status=status,
            event_payload=runtime_event_payload(
                event_instance,
                state=state,
                status=status,
                interrupts=interrupts,
                error=error,
                graph_messages=projection.context_messages,
                conversation_messages=projection.conversation_messages,
                tool_calls=projection.tool_calls,
            ),
            messages=projection.conversation_messages,
            tool_calls=projection.tool_calls,
            context_snapshot=self._conversation_context.execution_snapshot(
                claimed_instance,
                state=state,
                messages=projection.context_messages,
                status=status,
            ),
            model_usage=project_model_usage_records(claimed_instance, state.observability.events),
            error=error,
        )

    def _delegated_continuation_messages(
        self,
        *,
        instance: RuntimeInstance,
        graph: Any,
        current_messages: list[BaseMessage],
    ) -> tuple[list[BaseMessage], str] | None:
        if instance.request.runtime_role != "temporary" or instance.request.task_revision <= 1:
            return None
        task_id = str(instance.request.task_id or "").strip()
        if not task_id:
            raise RuntimeError("delegated task continuation requires a task identity")
        previous = self._delegations.previous_revision(
            principal_id=instance.request.principal_id,
            task_id=task_id,
            task_revision=instance.request.task_revision,
        )
        if previous.child_runtime.request.session_id != instance.request.session_id:
            raise RuntimeError("delegated task continuation changed conversation identity")
        if previous.child_runtime.request.strategy != instance.request.strategy:
            raise RuntimeError("delegated task continuation changed execution strategy")
        previous_thread_id = previous.child_runtime.runtime_instance_id
        previous_checkpoint = graph.graph_app.get_state(
            {"configurable": {"thread_id": previous_thread_id}}
        )
        previous_values = getattr(previous_checkpoint, "values", None) or {}
        previous_messages = list(previous_values.get("messages") or [])
        if not previous_messages:
            raise RuntimeError("delegated task continuation checkpoint is unavailable")
        return (
            [
                *close_terminal_tool_calls(previous_messages, status=previous.status),
                *current_messages,
            ],
            previous_thread_id,
        )

    def _delete_superseded_checkpoint(self, thread_id: str) -> None:
        try:
            deleted = delete_checkpoint_thread(self._service_set.services.checkpointer, thread_id)
            if not deleted:
                logger.warning(
                    "Checkpoint backend cannot delete superseded delegated task thread: thread_id=%s",
                    thread_id,
                )
        except Exception:
            logger.exception(
                "Failed to delete superseded delegated task checkpoint: thread_id=%s",
                thread_id,
            )

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

def _initial_state(
    *,
    instance: RuntimeInstance,
    snapshot: CapabilitySnapshot,
    current_user_message: ConversationMessage,
    launch_context: RuntimeLaunchContext,
    inherited_context_window: dict[str, Any] | None = None,
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
            temporal_context=launch_context.temporal_context,
            locale=launch_context.locale,
            capability_instructions=launch_context.capability_instructions,
            turn_directives=list(launch_context.turn_directives),
            attachments=[dict(item) for item in launch_context.attachments],
            workspace_root_alias=launch_context.workspace_root_alias,
            allow_external_paths=launch_context.allow_external_paths,
            workspace_mounts=[dict(item) for item in launch_context.workspace_mounts],
        ),
        conversation=ConversationState(
            current_user_input=_message_text(current_user_message),
            current_user_input_id=current_user_message.message_id,
        ),
        context=ContextState(
            token_budget=_inherited_token_budget(inherited_context_window),
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


def _inherited_token_budget(context_window: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context_window, dict):
        return {}
    token_count = context_window.get("token_count")
    if isinstance(token_count, bool) or not isinstance(token_count, (int, float)):
        return {}
    normalized_count = int(token_count)
    if normalized_count < 0:
        return {}
    method = str(context_window.get("token_count_method") or "provider_usage")
    source = str(context_window.get("source") or "runtime_checkpoint.inherited_context")
    inherited: dict[str, Any] = {
        "token_count": normalized_count,
        "token_count_method": method,
        "source": source,
        "effective_context_tokens": normalized_count,
        "effective_context_source": method,
        "last_provider_context_tokens_after_call": normalized_count,
        "last_provider_token_count_method": method,
        "inherited_context_baseline": True,
    }
    baseline_message_tokens = context_window.get("current_message_token_estimate")
    if (
        isinstance(baseline_message_tokens, (int, float))
        and not isinstance(baseline_message_tokens, bool)
        and baseline_message_tokens >= 0
    ):
        inherited["last_provider_message_tokens_after_call"] = int(baseline_message_tokens)
    return inherited


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
        or envelope.workspace_mode != instance.request.workspace_mode
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
    return "\n".join(item for item in chunks if item)


def _validate_invocation_status(instance: RuntimeInstance, *, resuming: bool) -> None:
    expected = {"waiting_approval", "waiting_external"} if resuming else {"queued"}
    if instance.status not in expected:
        action = "resume" if resuming else "execute"
        raise RuntimeError(
            f"cannot {action} runtime instance in status {instance.status!r}; "
            f"expected one of {sorted(expected)}"
        )


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
    final_content = final_graph_message_content(graph_messages)
    rendered = json.dumps(final_content, ensure_ascii=False) if not isinstance(final_content, str) else final_content
    if "DSML" in rendered and "tool_calls" in rendered:
        return "Temporary agent returned serialized tool markup instead of a native tool call."
    required_tools = tuple(instance.request.capability_requirements)
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


def _terminal_error(
    instance: RuntimeInstance,
    *,
    status: RuntimeExecutionStatus,
    state: RuntimeState,
) -> RuntimeErrorEnvelope | None:
    if status != "failed" and status != "cancelled":
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
) -> dict[str, Any]:
    if control.drain_requested:
        on_complete()
        return fallback_raw
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
                final_state = outcome.get("raw")
                if isinstance(final_state, dict):
                    control.acknowledge_checkpointed_inputs(
                        list(final_state.get("messages") or [])
                    )
        except BaseException as exc:
            control.restore_uncheckpointed_inputs()
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
    completed.wait()
    error = outcome.get("error")
    if control.drain_requested and isinstance(
        error, (RuntimeModelGenerationInterrupted, RuntimeToolExecutionCancelled)
    ):
        return dict(outcome["raw"])
    if error is not None:
        raise error
    return dict(outcome["raw"])
