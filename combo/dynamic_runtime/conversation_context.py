from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage, messages_from_dict, messages_to_dict

from combo.context_system.compression import is_context_summary_message, maybe_compress_messages
from combo.context_system.runtime import ContextSystemRuntime
from combo.context_system.token_counter import context_window_payload
from combo.context_system.token_estimation import estimate_messages_tokens
from combo.dynamic_runtime.context_snapshot_store import ConversationContextSnapshot, ConversationContextSnapshotStore
from combo.dynamic_runtime.conversation_projection import conversation_to_graph_messages
from combo.dynamic_runtime.model_service import RuntimeModelResolver
from combo.dynamic_runtime.policy_repositories import UserRuntimePolicyStore
from combo.dynamic_runtime.repositories import ConversationStore, RuntimeInstanceStore
from combo.dynamic_runtime.runtime_inspection import RuntimeInspectionService
from combo.dynamic_runtime.runtime_results import latest_context_window, non_negative_int
from combo.runtime_kernel.state import RuntimeState
from combo.runtime_protocol import ConversationMessage, RuntimeInstance
from combo.runtime_protocol.messages import incomplete_tool_call_ids, represented_input_message_ids


class ConversationContextService:
    """Own persisted conversation context, manual compression and snapshot projection."""

    def __init__(
        self,
        *,
        conversations: ConversationStore,
        context_snapshots: ConversationContextSnapshotStore,
        runtime_instances: RuntimeInstanceStore,
        runtime_policies: UserRuntimePolicyStore,
        model_resolver: RuntimeModelResolver,
        context_system: ContextSystemRuntime,
        inspection: RuntimeInspectionService,
    ) -> None:
        self._conversations = conversations
        self._context_snapshots = context_snapshots
        self._runtime_instances = runtime_instances
        self._runtime_policies = runtime_policies
        self._model_resolver = model_resolver
        self._context_system = context_system
        self._inspection = inspection

    def compress_main_context(
        self,
        *,
        session_id: str,
        principal_id: str,
    ) -> dict[str, Any]:
        identity = self._conversations.require_identity(session_id)
        if identity.principal_id != principal_id:
            raise PermissionError("conversation principal does not own the context snapshot")
        through_task_revision = self._conversations.compactable_task_revision(session_id)
        if through_task_revision is None:
            return {"status": "skipped", "reason": "no_completed_turns"}

        latest_runtime = self._runtime_instances.latest_completed_main(
            session_id=session_id,
            principal_id=principal_id,
        )
        if latest_runtime is None:
            return {"status": "skipped", "reason": "no_completed_runtime"}
        model_role = latest_runtime.request.policy_snapshot.model.operation

        try:
            current_policy = self._runtime_policies.require_for_principal(principal_id)
            compression_detail = current_policy.context_compression_detail
            keep_recent_messages = current_policy.context_compression_keep_recent_messages
        except LookupError:
            compression_detail = latest_runtime.request.policy_snapshot.context_compression_detail
            keep_recent_messages = (
                latest_runtime.request.policy_snapshot.context_compression_keep_recent_messages
            )

        graph_messages = self.session_messages(
            session_id=session_id,
            through_task_revision=through_task_revision,
        )
        if incomplete_tool_call_ids(graph_messages):
            raise RuntimeError("conversation context contains incomplete tool call history")

        limits = self._model_resolver.context_limits_for_snapshot(
            latest_runtime.request.policy_snapshot.model
        )
        latest_snapshot = self._context_snapshots.latest(session_id)
        if (
            latest_snapshot is not None
            and latest_snapshot.through_task_revision == through_task_revision
            and sum(not is_context_summary_message(message) for message in graph_messages)
            <= keep_recent_messages
        ):
            message_tokens = estimate_messages_tokens(graph_messages)
            window = _manual_compression_context_window(
                messages=graph_messages,
                limits=limits,
                model_role=model_role,
            )
            snapshot_updated_at = latest_snapshot.created_at
            if non_negative_int(latest_snapshot.context_window.get("token_count")) != message_tokens:
                corrected_snapshot = ConversationContextSnapshot(
                    session_id=session_id,
                    principal_id=principal_id,
                    through_task_revision=through_task_revision,
                    graph_messages=tuple(messages_to_dict(graph_messages)),
                    included_user_message_ids=latest_snapshot.included_user_message_ids,
                    context_window=window,
                    compression_report={
                        "status": "skipped",
                        "reason": "no_compressible_history",
                        "original_message_count": len(graph_messages),
                        "compressed_message_count": len(graph_messages),
                        "compacted_message_count": 0,
                        "token_estimate_before": message_tokens,
                        "token_estimate_after": message_tokens,
                    },
                )
                self._context_snapshots.append(corrected_snapshot)
                snapshot_updated_at = corrected_snapshot.created_at
            return {
                "status": "skipped",
                "reason": "no_compressible_history",
                "original_message_count": len(graph_messages),
                "compressed_message_count": len(graph_messages),
                "compacted_message_count": 0,
                "token_estimate_before": message_tokens,
                "token_estimate_after": message_tokens,
                "context_window": {**window, "updated_at": snapshot_updated_at},
            }

        context_runtime = self._context_system
        compression_policy = context_runtime.config.default_policy.compression.model_copy(
            update={
                "enabled": True,
                "trigger_token_threshold": limits.get("compression_threshold_tokens"),
                "detail": compression_detail,
                "keep_recent_messages": keep_recent_messages,
            }
        )

        main_model = self._model_resolver.resolve_for_instance(latest_runtime)
        compression_model = self._model_resolver.resolve_compression_for_instance(
            latest_runtime,
            fallback=main_model,
        )
        compressed_messages, report = maybe_compress_messages(
            messages=graph_messages,
            policy=compression_policy,
            node_id="manual_context_compression",
            summary_model=compression_model.model,
            summary_model_max_output_tokens=compression_model.settings.max_output_tokens,
            summary_model_metadata=compression_model.settings.metadata(),
            force=True,
        )
        report_payload = report.model_dump(mode="json")
        if report.status == "failed":
            raise RuntimeError(report.error or "manual context compression failed")
        if report.status != "completed":
            return {**report_payload, "reason": report.reason or "no_compressible_history"}

        window = _manual_compression_context_window(
            messages=compressed_messages,
            limits=limits,
            model_role=model_role,
        )
        snapshot = ConversationContextSnapshot(
            session_id=session_id,
            principal_id=principal_id,
            through_task_revision=through_task_revision,
            graph_messages=tuple(messages_to_dict(compressed_messages)),
            included_user_message_ids=latest_snapshot.included_user_message_ids if latest_snapshot else (),
            context_window=window,
            compression_report=report_payload,
        )
        self._context_snapshots.append(snapshot)
        return {
            **report_payload,
            "snapshot_id": snapshot.snapshot_id,
            "context_window": {**window, "updated_at": snapshot.created_at},
        }

    def inherited_context_window(self, instance: RuntimeInstance) -> dict[str, Any] | None:
        if instance.request.runtime_role != "main":
            return None
        context_snapshot = self._context_snapshots.latest(instance.request.session_id)
        if (
            context_snapshot is not None
            and context_snapshot.through_task_revision < instance.request.task_revision
        ):
            return dict(context_snapshot.context_window)
        previous = self._runtime_instances.latest_completed_main_before(
            session_id=instance.request.session_id,
            principal_id=instance.request.principal_id,
            created_at=instance.created_at,
        )
        if previous is None:
            return None
        return self._inspection.current_context_window(previous.runtime_instance_id)

    def session_messages(
        self,
        *,
        session_id: str,
        through_task_revision: int,
        canonical_messages: list[ConversationMessage] | None = None,
        runtime_role: str = "main",
    ) -> list[BaseMessage]:
        if runtime_role != "main":
            return conversation_to_graph_messages(list(canonical_messages or []))
        snapshot = self._context_snapshots.latest(session_id)
        if snapshot is None or snapshot.through_task_revision > through_task_revision:
            source_messages = canonical_messages
            if source_messages is None:
                source_messages = self._conversations.messages_through_task_revision(
                    session_id=session_id,
                    task_revision=through_task_revision,
                )
            return conversation_to_graph_messages(source_messages)
        delta = self._conversations.messages_between_task_revisions(
            session_id=session_id,
            after_task_revision=snapshot.through_task_revision,
            through_task_revision=through_task_revision,
        )
        return [
            *messages_from_dict(list(snapshot.graph_messages)),
            *conversation_to_graph_messages([message for message in delta if message.message_id not in snapshot.included_user_message_ids]),
        ]

    def execution_snapshot(
        self, instance: RuntimeInstance, *, state: RuntimeState, messages: list[Any], status: str,
    ) -> ConversationContextSnapshot | None:
        if instance.request.runtime_role != "main" or status not in {"completed", "failed", "cancelled"}:
            return None
        previous = self._context_snapshots.latest(instance.request.session_id)
        if previous is None and not any(
            is_context_summary_message(message)
            or message.additional_kwargs.get("kind") == "runtime_steered_input"
            for message in messages
        ):
            return None
        included = set(previous.included_user_message_ids if previous else ())
        included.update(represented_input_message_ids(messages))
        return ConversationContextSnapshot(
            session_id=instance.request.session_id,
            principal_id=instance.request.principal_id,
            through_task_revision=instance.request.task_revision,
            graph_messages=tuple(messages_to_dict(messages)),
            included_user_message_ids=tuple(sorted(included)),
            context_window=latest_context_window(state, graph_messages=messages) or {},
            compression_report=state.context.compression_report or (previous.compression_report if previous else {}),
        )


def _manual_compression_context_window(
    *,
    messages: list[Any],
    limits: dict[str, Any],
    model_role: str,
) -> dict[str, Any]:
    message_tokens = estimate_messages_tokens(messages)
    window = context_window_payload(
        node_id="manual_context_compression",
        token_count=message_tokens,
        token_count_method="text_estimation",
        compression_threshold_tokens=limits.get("compression_threshold_tokens"),
        context_window_tokens=limits.get("context_window_tokens"),
        model_role=model_role,
        source="context_system.manual_compression",
    )
    window["current_message_token_estimate"] = message_tokens
    return window

