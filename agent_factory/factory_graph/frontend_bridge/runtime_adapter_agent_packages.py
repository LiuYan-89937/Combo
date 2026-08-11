from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer, json_safe
from agent_factory.factory_graph.frontend_bridge.protocol import (
    FactoryFrontendCommand,
    FactoryFrontendEvent,
    FactoryMode,
    event,
)
from agent_factory.factory_graph.frontend_bridge.runtime_events import (
    INTERRUPT_TERMINAL_EVENT_TYPES,
    RUN_TERMINAL_EVENT_TYPES,
    runtime_stream_status,
)
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import (
    VisibleAssistantOutputAccumulator,
    extract_interrupt_payload,
    interrupt_accepts_message,
    message_resume_command,
)
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import (
    PendingAgentPackageRun,
)
from agent_factory.runtime_attachments import (
    AttachmentImportError,
    attachment_import_error_payload,
    has_attachment_payload,
)
from agent_factory.runtime_protocol.completion import runtime_completed, runtime_error_message


@dataclass(frozen=True, slots=True)
class RuntimeStreamConsumeResult:
    status: str
    terminal_event: FactoryFrontendEvent | None = None
    message: str = ""
    payload: dict[str, Any] | None = None
    final_answer: str = ""
    reasoning_content: str = ""
    tool_activities: list[dict[str, Any]] = field(default_factory=list)


class RuntimeAgentPackageCommandMixin:
    def list_agent_packages(self, command: FactoryFrontendCommand) -> None:
        packages = self.agent_package_runtime.list_packages()
        self.emit(
            event(
                "agent_packages_listed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode="agent_package",
                payload={"packages": packages},
            )
        )

    def select_agent_package(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        if not package_id:
            self._emit_error(command, "select_agent_package requires package_id")
            return
        package_info = self.agent_package_runtime.package_summary(package_id)
        sessions = self.agent_package_runtime.list_sessions(package_id)
        self.mode = "agent_package"
        self.emit(
            event(
                "agent_package_selected",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode="agent_package",
                payload={"package": package_info, "sessions": sessions},
            )
        )

    def delete_agent_package(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        if not package_id:
            self._emit_error(command, "delete_agent_package requires package_id")
            return
        result = self.agent_package_runtime.delete_package(package_id)
        packages = self.agent_package_runtime.list_packages()
        self.emit(
            event(
                "agent_package_deleted",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode="agent_package",
                payload={**result, "packages": packages},
            )
        )

    def initialize_agent_package(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        if not package_id:
            self._emit_error(command, "initialize_agent_package requires package_id")
            return
        self.agent_package_runtime.initialize_package(package_id, request_id=command.request_id)

    def shutdown_agent_package_instance(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        if not package_id:
            self._emit_error(command, "shutdown_agent_package_instance requires package_id")
            return
        self.agent_package_runtime.shutdown_package_instance(package_id, request_id=command.request_id)

    def list_agent_package_instances(self, command: FactoryFrontendCommand) -> None:
        statuses = self.agent_package_runtime.list_instance_statuses()
        self.emit(
            event(
                "agent_package_instances_listed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode="agent_package",
                payload={"instances": statuses},
            )
        )

    def list_agent_package_sessions(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        if not package_id:
            self._emit_error(command, "list_agent_package_sessions requires package_id")
            return
        sessions = self.agent_package_runtime.list_sessions(package_id)
        self.emit(
            event(
                "agent_package_sessions_listed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode="agent_package",
                payload={"package_id": package_id, "sessions": sessions},
            )
        )

    def load_agent_package_session(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        session_id = str(command.payload.get("session_id") or "").strip()
        if not package_id:
            self._emit_error(command, "load_agent_package_session requires package_id")
            return
        if not session_id:
            self._emit_error(command, "load_agent_package_session requires session_id")
            return
        session = self.agent_package_runtime.load_session(package_id, session_id)
        self.emit(
            event(
                "agent_package_session_loaded",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode="agent_package",
                payload={"package_id": package_id, "session_id": session_id, "session": session},
            )
        )

    def delete_agent_package_session(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        session_id = str(command.payload.get("session_id") or command.session_id or "").strip()
        if not package_id:
            self._emit_error(command, "delete_agent_package_session requires package_id")
            return
        if not session_id:
            self._emit_error(command, "delete_agent_package_session requires session_id")
            return
        result = self.agent_package_runtime.delete_session(package_id, session_id)
        self.emit(
            event(
                "agent_package_session_deleted",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode="agent_package",
                payload=result,
            )
        )

    def run_agent_package(self, command: FactoryFrontendCommand) -> None:
        self._send_agent_package_message(command, require_ready=False)

    def run_agent_group_member(self, command: FactoryFrontendCommand) -> None:
        """Run one persisted agent-group member through the standard runtime stream."""
        from agent_factory.agent_group_system.store import AgentGroupStore

        group_id = str(command.payload.get("group_id") or "").strip()
        group_run_id = str(command.payload.get("group_run_id") or "").strip()
        message = str(command.payload.get("message") or command.message or "").strip()
        if not group_id or not group_run_id or not message:
            self._emit_error(command, "run_agent_group_member requires group_id, group_run_id, and message")
            return

        store = AgentGroupStore()
        group_run = store.get_run(group_run_id)
        if group_run is None or str(group_run.get("group_id") or "") != group_id:
            self._emit_error(command, "agent group run not found")
            return
        if str(group_run.get("status") or "") not in {"queued", "running"}:
            self._emit_error(command, "agent group run is not dispatchable")
            return

        package_id = str(group_run.get("speaker_package_id") or "").strip()
        package_session_id = str(group_run.get("package_session_id") or "").strip()
        if not package_id or not package_session_id:
            self._emit_error(command, "agent group run is missing its member session")
            return

        group_payload = {
            "group_id": group_id,
            "group_run_id": group_run_id,
            "group_message_id": str(group_run.get("message_id") or ""),
            "package_id": package_id,
            "package_session_id": package_session_id,
            "context_version": int(command.payload.get("context_version") or 0),
        }
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=package_session_id,
            mode="agent_group",
            graph_id="agent_group",
            producer_type="agent_group_runtime",
            default_payload=dict(group_payload),
        )
        store.update_run(group_run_id, {"status": "running"})
        try:
            stream_run = self.agent_package_runtime.stream(
                package_id,
                user_input=message,
                display_user_input=str(command.payload.get("display_user_input") or "").strip() or None,
                session_id=package_session_id,
                request_id=command.request_id,
                user_config=_runtime_user_config(command),
                message_metadata={"agent_group": group_payload},
                session_kind="agent_group_member",
                agent_group_id=group_id,
                visible_in_agent_session_list=False,
                workdir_root=store.group_staging_root(group_id, group_run_id),
            )
            result = self._consume_agent_package_stream(
                package_id=package_id,
                run=stream_run,
                normalizer=normalizer,
                frontend_mode="agent_group",
                frontend_session_id=package_session_id,
                extra_payload=group_payload,
            )
            self._persist_agent_package_stream_result(
                package_id=package_id,
                run=stream_run,
                result=result,
                request_id=command.request_id,
            )
            if result.status in {"completed", "failed", "cancelled", "stopped"}:
                store.update_run(group_run_id, {"status": result.status})
        except Exception as exc:
            self.agent_package_runtime.finish_session_turn(
                package_id,
                session_id=package_session_id,
                request_id=command.request_id,
                final_answer=None,
                status="failed",
            )
            store.update_run(group_run_id, {"status": "failed"})
            normalizer.emit_run_failed(exc)

    def send_agent_package_message(self, command: FactoryFrontendCommand) -> None:
        self._send_agent_package_message(command, require_ready=True)

    def _send_agent_package_message(self, command: FactoryFrontendCommand, *, require_ready: bool) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        message = str(command.payload.get("message") or command.message or "").strip()
        display_user_input = str(command.payload.get("display_user_input") or "").strip() or None
        session_id = str(command.payload.get("session_id") or "").strip() or None
        if not package_id:
            self._emit_error(command, f"{command.type} requires package_id")
            return
        if not message and not has_attachment_payload(command.payload.get("attachments")):
            self._emit_error(command, f"{command.type} requires message")
            return
        if session_id and self._has_pending_agent_package_run(package_id, session_id):
            pending = self._take_pending_agent_package_for_message(package_id, session_id)
            if pending is not None and interrupt_accepts_message(pending):
                self._resume_agent_package_interrupt(message_resume_command(command, message), pending)
            else:
                if pending is not None:
                    self._remember_pending_agent_package_run(pending)
                self._emit_error(command, "cannot send an agent package message while an interrupt decision is pending")
            return
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=self._session_id(),
            mode="agent_package",
            graph_id="agent_package_runtime",
        )
        try:
            run = self.agent_package_runtime.stream(
                package_id,
                user_input=message,
                display_user_input=display_user_input,
                session_id=session_id,
                request_id=command.request_id,
                user_config=_runtime_user_config(command),
                runtime_request=_runtime_request(command),
                message_metadata=(
                    dict(command.payload["message_metadata"])
                    if isinstance(command.payload.get("message_metadata"), dict)
                    else None
                ),
                require_ready=require_ready,
                attachments=command.payload.get("attachments"),
                workspace_id=str(command.payload.get("workspace_id") or "").strip() or None,
            )
            result = self._consume_agent_package_stream(package_id=package_id, run=run, normalizer=normalizer)
            self._persist_agent_package_stream_result(
                package_id=package_id,
                run=run,
                result=result,
                request_id=command.request_id,
            )
        except AttachmentImportError as exc:
            _emit_attachment_import_failed(normalizer, exc)
        except Exception as exc:
            normalizer.emit_run_failed(exc)

    def _resume_agent_package_interrupt(
        self,
        command: FactoryFrontendCommand,
        pending: PendingAgentPackageRun,
    ) -> None:
        try:
            run = self.agent_package_runtime.resume_stream(
                pending.package_id,
                session_id=pending.session_id,
                resume_payload=command.payload,
                request_id=command.request_id,
                runtime_request=_runtime_request(command),
            )
            result = self._consume_agent_package_stream(
                package_id=pending.package_id,
                run=run,
                normalizer=pending.normalizer,
            )
            self._persist_agent_package_stream_result(
                package_id=pending.package_id,
                run=run,
                result=result,
                request_id=result.terminal_event.request_id if result.terminal_event else command.request_id,
            )
        except Exception as exc:
            pending.normalizer.emit_run_failed(exc)

    def resume_agent_group_interrupt(self, command: FactoryFrontendCommand, pending: PendingAgentPackageRun) -> None:
        """Resume one group member without crossing into the normal package pending slot."""
        try:
            pending.normalizer.request_id = command.request_id
            run = self.agent_package_runtime.resume_stream(
                pending.package_id,
                session_id=pending.session_id,
                resume_payload=command.payload,
                request_id=command.request_id,
                workdir_root=pending.workdir_root,
            )
            group_payload = {
                "group_id": pending.group_id,
                "group_run_id": pending.group_run_id,
                "package_id": pending.package_id,
                "package_session_id": pending.session_id,
            }
            result = self._consume_agent_package_stream(
                package_id=pending.package_id,
                run=run,
                normalizer=pending.normalizer,
                frontend_mode="agent_group",
                frontend_session_id=pending.session_id,
                extra_payload=group_payload,
            )
            self._persist_agent_package_stream_result(
                package_id=pending.package_id,
                run=run,
                result=result,
                request_id=result.terminal_event.request_id if result.terminal_event else command.request_id,
            )
        except Exception as exc:
            pending.normalizer.emit_run_failed(exc)

    def cancel_runtime_request(self, command: FactoryFrontendCommand) -> None:
        reason = str(command.payload.get("reason") or "user_cancelled")
        target_request_id = str(command.payload.get("target_request_id") or "").strip() or None
        cancelled = (
            self.agent_package_runtime.cancel_active_requests(
                reason=reason,
                request_id=target_request_id,
            )
            if self.agent_package_runtime
            else 0
        )
        if self.agent_package_runtime is not None:
            cancelled += int(self.agent_package_runtime.cancel_extension_request(target_request_id))
        if target_request_id and cancelled:
            self.emit(
                event(
                    "node_progress",
                    request_id=target_request_id,
                    session_id=str(command.session_id or self._session_id() or "").strip() or None,
                    mode=command.mode or self.mode,
                    graph_id="factory_runtime",
                    producer_type="factory_runtime",
                    node_id="runtime_request",
                    node_label="Runtime Request",
                    node_kind="control",
                    payload={
                        "status": "stopping",
                        "stop_reason": reason,
                        "dispatch_state": "stopping",
                    },
                )
            )
        self.emit(
            event(
                "debug_patch",
                request_id=command.request_id,
                session_id=command.session_id or self._session_id(),
                mode=command.mode or self.mode,
                graph_id="factory_runtime",
                producer_type="factory_runtime",
                payload={
                    "source": "runtime_request_cancel",
                    "reason": reason,
                    "target_request_id": target_request_id,
                    "cancelled_requests": cancelled,
                },
            )
        )

    def _consume_agent_package_stream(
        self,
        *,
        package_id: str,
        run: Any,
        normalizer: RuntimeEventNormalizer,
        frontend_mode: FactoryMode | None = None,
        frontend_session_id: str | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> RuntimeStreamConsumeResult:
        request_id = run.request_id
        normalizer.default_payload = {**normalizer.default_payload, "package_id": package_id}
        final_state = None
        terminal_event: FactoryFrontendEvent | None = None
        visible_output = VisibleAssistantOutputAccumulator()
        for stream_mode, chunk in run.events:
            if terminal_event is not None:
                continue
            if stream_mode == "frontend_event":
                item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
                visible_output.accept(item)
                agent_session_id = item.session_id
                if agent_session_id:
                    run.session["session_id"] = agent_session_id
                event_extra_payload = dict(extra_payload or {})
                if item.event_type == "run_started" and isinstance(run.session, dict):
                    event_extra_payload["agent_session"] = dict(run.session)
                if item.event_type in INTERRUPT_TERMINAL_EVENT_TYPES:
                    session_id = str(agent_session_id or (run.session or {}).get("session_id") or "")
                    if not session_id:
                        raise RuntimeError("agent package interrupt missing session_id")
                    pending = PendingAgentPackageRun(
                        package_id=package_id,
                        session_id=session_id,
                        normalizer=normalizer,
                        interrupt_id=_interrupt_id_from_event(item),
                        interrupt_event_id=item.event_id,
                        interrupt_payload=_interrupt_payload(item.payload),
                    )
                    def commit_interrupt() -> None:
                        if frontend_mode == "agent_group" and extra_payload:
                            from agent_factory.agent_group_system.store import AgentGroupStore

                            pending.group_id = str(extra_payload.get("group_id") or "") or None
                            pending.group_run_id = str(extra_payload.get("group_run_id") or "") or None
                            if pending.group_id and pending.group_run_id:
                                pending.workdir_root = AgentGroupStore().group_staging_root(
                                    pending.group_id,
                                    pending.group_run_id,
                                )
                                self.pending_agent_group_runs[pending.group_run_id] = pending
                            else:
                                self._remember_pending_agent_package_run(pending)
                        else:
                            self._remember_pending_agent_package_run(pending)

                        self.emit(
                            _frontend_scoped_agent_event(
                                item,
                                mode=frontend_mode,
                                session_id=frontend_session_id,
                                package_id=package_id,
                                extra_payload=event_extra_payload,
                            )
                        )

                    commit_interrupt()
                    terminal_event = item
                    continue
                self.emit(
                    _frontend_scoped_agent_event(
                        item,
                        mode=frontend_mode,
                        session_id=frontend_session_id,
                        package_id=package_id,
                        extra_payload=event_extra_payload,
                    )
                )
                if item.event_type in RUN_TERMINAL_EVENT_TYPES:
                    terminal_event = item
                continue
            if stream_mode == "stderr":
                normalizer.runtime_event(
                    "debug_patch",
                    span_id=normalizer.run_span_id,
                    payload={"agent_package_stderr": json_safe(chunk)},
                )
                continue
            interrupt_payload = extract_interrupt_payload(chunk)
            if interrupt_payload is not None:
                session_id = str((run.session or {}).get("session_id") or "")
                if not session_id:
                    raise RuntimeError("agent package interrupt missing session_id")
                pending = PendingAgentPackageRun(
                    package_id=package_id,
                    session_id=session_id,
                    normalizer=normalizer,
                    interrupt_id=_interrupt_id_from_payload(interrupt_payload),
                    interrupt_payload=_interrupt_payload(interrupt_payload),
                )
                payload = json_safe(interrupt_payload)
                if isinstance(payload, dict):
                    payload = {**payload, "package_id": package_id}
                def commit_interrupt() -> None:
                    self._remember_pending_agent_package_run(pending)
                    normalizer.emit_interrupt(payload)

                commit_interrupt()
                return RuntimeStreamConsumeResult(
                    status="interrupted",
                    final_answer=visible_output.content,
                    reasoning_content=visible_output.reasoning_content,
                    tool_activities=list(visible_output.tool_activities),
                )
            if stream_mode == "runtime_final":
                final_state = chunk
                continue
            normalizer.emit_stream_item(stream_mode, chunk, updates_payload_key="agent_package_update")
        if terminal_event is not None:
            return RuntimeStreamConsumeResult(
                status=runtime_stream_status(terminal_event),
                terminal_event=terminal_event,
                final_answer=visible_output.content,
                reasoning_content=visible_output.reasoning_content,
                tool_activities=list(visible_output.tool_activities),
            )
        if final_state is None:
            raise RuntimeError("agent package runtime did not produce a final state")
        if not runtime_completed(final_state):
            message = runtime_error_message(final_state, command="agent package runtime")
            normalizer.complete_open_model_streams(reason="run_failed")
            normalizer.emit_run_failed(RuntimeError(message))
            return RuntimeStreamConsumeResult(
                status="failed",
                message=message,
                final_answer=visible_output.content,
                reasoning_content=visible_output.reasoning_content,
                tool_activities=list(visible_output.tool_activities),
            )
        normalizer.complete_visible_assistant_output_from_state(final_state, reason="run_completed")
        normalizer.emit_run_completed(
            {
                "status": final_state.execution.finish_status,
                "package_id": package_id,
                "agent_id": run.package.assembly_spec.agent.id,
                "agent_session": run.session,
                "final_answer": visible_output.content,
            }
        )
        return RuntimeStreamConsumeResult(
            status="completed",
            final_answer=visible_output.content,
            reasoning_content=visible_output.reasoning_content,
            tool_activities=list(visible_output.tool_activities),
        )

    def _persist_agent_package_stream_result(
        self,
        *,
        package_id: str,
        run: Any,
        result: RuntimeStreamConsumeResult,
        request_id: str | None,
    ) -> None:
        terminal_payload = (
            result.terminal_event.payload
            if result.terminal_event is not None and isinstance(result.terminal_event.payload, dict)
            else {}
        )
        terminal_session = terminal_payload.get("agent_session")
        terminal_session_id = (
            str(terminal_session.get("session_id") or "").strip()
            if isinstance(terminal_session, dict)
            else ""
        )
        run_session = run.session if isinstance(run.session, dict) else {}
        session_id = terminal_session_id or str(run_session.get("session_id") or "").strip()
        if not session_id:
            raise RuntimeError("agent package stream result is missing its runtime session_id")
        self.agent_package_runtime.finish_session_turn(
            package_id,
            session_id=session_id,
            request_id=request_id,
            final_answer=result.final_answer,
            reasoning_content=result.reasoning_content,
            status=result.status,
            tool_activities=result.tool_activities,
        )

def _frontend_scoped_agent_event(
    item: FactoryFrontendEvent,
    *,
    mode: FactoryMode | None,
    session_id: str | None,
    package_id: str | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> FactoryFrontendEvent:
    updates: dict[str, Any] = {}
    if mode is not None:
        updates["mode"] = mode
    if session_id is not None:
        updates["session_id"] = session_id
    if package_id is not None or extra_payload:
        updates["payload"] = {
            **(item.payload if isinstance(item.payload, dict) else {}),
            **({"package_id": package_id} if package_id is not None else {}),
            **(extra_payload or {}),
        }
    return item.model_copy(update=updates) if updates else item


def _runtime_user_config(command: FactoryFrontendCommand) -> dict[str, Any]:
    payload = command.payload if isinstance(command.payload, dict) else {}
    user_config = payload.get("user_config")
    return dict(user_config) if isinstance(user_config, dict) else {}


def _runtime_request(command: FactoryFrontendCommand) -> dict[str, Any] | None:
    payload = command.payload if isinstance(command.payload, dict) else {}
    runtime_request = payload.get("runtime_request")
    return dict(runtime_request) if isinstance(runtime_request, dict) else None


def _resume_payload_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload or "").strip()
    for key in ("input_text", "answer", "message", "revision_guidance"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _emit_attachment_import_failed(normalizer: RuntimeEventNormalizer, exc: AttachmentImportError) -> None:
    payload = attachment_import_error_payload(exc)
    normalizer.runtime_event(
        "run_failed",
        span_id=normalizer.run_span_id,
        severity="error",
        message=payload["message"],
        payload=payload,
    )


def _interrupt_id_from_event(item: FactoryFrontendEvent) -> str | None:
    return _interrupt_id_from_payload(item.payload if isinstance(item.payload, dict) else {})


def _interrupt_id_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    interrupt_id = str(payload.get("interrupt_id") or "").strip()
    return interrupt_id or None


def _interrupt_payload(payload: Any) -> dict[str, Any]:
    return dict(payload) if isinstance(payload, dict) else {}
