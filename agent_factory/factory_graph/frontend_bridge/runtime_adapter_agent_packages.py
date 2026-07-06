from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

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
)
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import (
    PendingAgentPackageRun,
    PendingCreateAgentRun,
    PendingEvolutionRun,
    SYSTEM_CHAT_PACKAGE_ID,
)
from agent_factory.runtime_attachments import (
    AttachmentImportError,
    attachment_import_error_payload,
    has_attachment_payload,
    redact_attachment_markers,
    transcript_attachment_views,
)
from agent_factory.runtime_protocol.completion import runtime_completed, runtime_error_message


@dataclass(frozen=True, slots=True)
class RuntimeStreamConsumeResult:
    status: str
    terminal_event: FactoryFrontendEvent | None = None
    message: str = ""
    payload: dict[str, Any] | None = None


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
        purpose = str(command.payload.get("purpose") or "").strip()
        if not package_id:
            self._emit_error(command, "select_agent_package requires package_id")
            return
        package_info = self.agent_package_runtime.package_summary(package_id)
        if purpose == "evolution":
            self._select_evolution_agent_package(command, package_id=package_id, package_info=package_info)
            return
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

    def _select_evolution_agent_package(
        self,
        command: FactoryFrontendCommand,
        *,
        package_id: str,
        package_info: dict[str, Any],
    ) -> None:
        self._ensure_evolution_package_session(command, package_id)
        trace_payload: dict[str, Any] = {}
        try:
            trace_payload["latest_failed_trace_id"] = self.evolution_runtime.latest_failed_trace_id(package_id)
        except Exception as exc:
            trace_payload["latest_failed_trace_error"] = f"{type(exc).__name__}: {exc}"
        self.emit(
            event(
                "agent_package_selected",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode="evolve_agent",
                payload={
                    "package": package_info,
                    "package_id": package_id,
                    "session": self._session_payload(),
                    "sessions": [],
                    "purpose": "evolution",
                    **trace_payload,
                },
            )
        )

    def _ensure_evolution_package_session(self, command: FactoryFrontendCommand, package_id: str) -> None:
        normalized_package_id = package_id.strip()
        if not normalized_package_id:
            raise ValueError("evolution package_id is required")

        current_package_id = (
            str(getattr(self.session_record, "evolve_agent_package_id", "") or "").strip()
            if self.session_record is not None
            else ""
        )
        current_is_blank_evolution = (
            self.session_record is not None
            and self.session_record.current_mode == "evolve_agent"
            and not current_package_id
            and not self.session_record.evolve_agent_turns
        )
        if self.session_record is None:
            existing = self.session_manager.latest_evolution_for_package(normalized_package_id)
            self.session_record = existing or self.session_manager.create(mode="evolve_agent")
        elif current_package_id != normalized_package_id and not current_is_blank_evolution:
            existing = self.session_manager.latest_evolution_for_package(normalized_package_id)
            self.session_record = existing or self.session_manager.create(mode="evolve_agent")

        self.mode = "evolve_agent"
        self.evolution_package_id = normalized_package_id
        self.session_record = self.session_manager.set_evolution_package(
            self.session_record.session_id,
            normalized_package_id,
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
        if self.pending_agent_package_run is not None:
            self._emit_error(command, "cannot send an agent package message while an interrupt is pending")
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
                require_ready=require_ready,
                attachments=command.payload.get("attachments"),
            )
            self._consume_agent_package_stream(package_id=package_id, run=run, normalizer=normalizer)
        except AttachmentImportError as exc:
            _emit_attachment_import_failed(normalizer, exc)
        except Exception as exc:
            normalizer.emit_run_failed(exc)

    def run_agent_evolution(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or self.evolution_package_id or "").strip()
        message = str(command.payload.get("message") or command.message or "").strip()
        if not package_id:
            self._emit_error(command, "run_agent_evolution requires package_id")
            return
        if not message and not has_attachment_payload(command.payload.get("attachments")):
            self._emit_error(command, "run_agent_evolution requires message")
            return
        if self.pending_evolution_run is not None:
            self._emit_error(command, "cannot evolve an agent while an interrupt is pending")
            return
        self._ensure_evolution_package_session(command, package_id)
        redacted_message = redact_attachment_markers(message)
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=self._session_id(),
            mode="evolve_agent",
            graph_id="agent_evolution",
            producer_type="factory_runtime",
        )
        try:
            self._commit_evolution_request(
                redacted_message,
                package_id=package_id,
                request_id=command.request_id,
                attachments=transcript_attachment_views(command.payload.get("attachments")),
            )
            run = self.evolution_runtime.stream(
                package_id=package_id,
                user_input=message,
                request_id=command.request_id,
                session_id=self._session_id(),
                user_config=_runtime_user_config(command),
                attachments=command.payload.get("attachments"),
            )
            self._consume_evolution_stream(package_id=package_id, run=run)
        except AttachmentImportError as exc:
            _emit_attachment_import_failed(normalizer, exc)
            self._finish_evolution_turn(request_id=command.request_id, final_answer=None, status="failed")
        except Exception as exc:
            normalizer.emit_run_failed(exc)
            self._finish_evolution_turn(request_id=command.request_id, final_answer=None, status="failed")

    def _run_evolve_agent(self, command: FactoryFrontendCommand, message: str) -> None:
        package_id = self.evolution_package_id or str(command.payload.get("package_id") or "").strip()
        if not package_id:
            self._emit_error(command, "select an agent with /evolve-agent before sending evolution requests")
            return
        self.run_agent_evolution(
            FactoryFrontendCommand(
                type="run_agent_evolution",
                request_id=command.request_id,
                session_id=command.session_id,
                message=message,
                payload={
                    "package_id": package_id,
                    "message": message,
                    **(
                        {"user_config": command.payload.get("user_config")}
                        if command.payload.get("user_config")
                        else {}
                    ),
                    **({"attachments": command.payload.get("attachments")} if command.payload.get("attachments") else {}),
                },
            )
        )

    def _consume_evolution_stream(self, *, package_id: str, run: Any) -> RuntimeStreamConsumeResult:
        terminal_event: FactoryFrontendEvent | None = None
        visible_output = VisibleAssistantOutputAccumulator()
        for stream_mode, chunk in run.events:
            if terminal_event is not None:
                continue
            if stream_mode != "frontend_event":
                continue
            item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
            visible_output.accept(item)
            if item.event_type in INTERRUPT_TERMINAL_EVENT_TYPES:
                session_id = self._session_id()
                if not session_id:
                    raise RuntimeError("agent evolution interrupt missing session_id")
                self._finish_evolution_turn(
                    request_id=item.request_id,
                    final_answer=visible_output.content,
                    reasoning_content=visible_output.reasoning_content,
                    status="interrupted",
                )
                self.pending_evolution_run = PendingEvolutionRun(
                    package_id=package_id,
                    session_id=session_id,
                    request_id=item.request_id,
                    trace_id=run.trace_id,
                    interrupt_id=_interrupt_id_from_event(item),
                    interrupt_event_id=item.event_id,
                )
                self.emit(
                    _frontend_scoped_agent_event(
                        item,
                        mode="evolve_agent",
                        session_id=session_id,
                        package_id=package_id,
                    )
                )
                terminal_event = item
                continue
            self.emit(
                _frontend_scoped_agent_event(
                    item,
                    mode="evolve_agent",
                    session_id=self._session_id(),
                    package_id=package_id,
                )
            )
            if item.event_type in RUN_TERMINAL_EVENT_TYPES:
                self._finish_evolution_turn(
                    request_id=item.request_id,
                    final_answer=visible_output.content,
                    reasoning_content=visible_output.reasoning_content,
                    status=runtime_stream_status(item),
                )
                terminal_event = item
        if terminal_event is not None:
            return RuntimeStreamConsumeResult(status=runtime_stream_status(terminal_event), terminal_event=terminal_event)
        raise RuntimeError("agent evolution runtime stream ended without a terminal event")

    def _resume_agent_package_interrupt(self, command: FactoryFrontendCommand) -> None:
        pending = self.pending_agent_package_run
        self.pending_agent_package_run = None
        if pending is None:
            self._emit_error(command, "no pending agent package interrupt to resume")
            return
        try:
            run = self.agent_package_runtime.resume_stream(
                pending.package_id,
                session_id=pending.session_id,
                resume_payload=command.payload,
                request_id=command.request_id,
            )
            self._consume_agent_package_stream(
                package_id=pending.package_id,
                run=run,
                normalizer=pending.normalizer,
                frontend_mode=pending.normalizer.mode if pending.normalizer.mode == "chat" else None,
                frontend_session_id=pending.normalizer.session_id if pending.normalizer.mode == "chat" else None,
            )
        except Exception as exc:
            pending.normalizer.emit_run_failed(exc)

    def _resume_create_agent_interrupt(self, command: FactoryFrontendCommand) -> None:
        pending = self.pending_create_agent_run
        self.pending_create_agent_run = None
        if pending is None:
            self._emit_error(command, "no pending create-agent interrupt to resume")
            return
        resume_text = _resume_payload_text(command.payload)
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=self._session_id(),
            mode="create_agent",
            graph_id="create_agent_react",
            producer_type="factory_runtime",
        )
        try:
            if resume_text:
                self.session_record = self.session_manager.start_turn(
                    self.session_record.session_id,
                    "create_agent",
                    request_id=command.request_id,
                    user_input=resume_text,
                )
            run = self.create_agent_runtime.resume_stream(
                session_id=pending.session_id,
                resume_payload=command.payload,
                request_id=command.request_id,
            )
            self._consume_create_agent_stream(run=run)
        except Exception as exc:
            normalizer.emit_run_failed(exc)
            self._finish_host_create_agent_turn(request_id=command.request_id, final_answer=None, status="failed")

    def _resume_evolution_interrupt(self, command: FactoryFrontendCommand) -> None:
        pending = self.pending_evolution_run
        self.pending_evolution_run = None
        if pending is None:
            self._emit_error(command, "no pending evolution interrupt to resume")
            return
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=self._session_id(),
            mode="evolve_agent",
            graph_id="agent_evolution",
            producer_type="factory_runtime",
        )
        try:
            run = self.evolution_runtime.resume_stream(
                package_id=pending.package_id,
                session_id=pending.session_id,
                resume_payload=command.payload,
                request_id=command.request_id,
            )
            self._consume_evolution_stream(package_id=pending.package_id, run=run)
        except Exception as exc:
            normalizer.emit_run_failed(exc)

    def cancel_runtime_request(self, command: FactoryFrontendCommand) -> None:
        reason = str(command.payload.get("reason") or "user_cancelled")
        target_request_id = str(command.payload.get("target_request_id") or "").strip() or None
        visible_output = command.payload.get("visible_output") if isinstance(command.payload.get("visible_output"), dict) else None
        cancelled = (
            self.agent_package_runtime.cancel_active_requests(
                reason=reason,
                request_id=target_request_id,
                visible_output=visible_output,
            )
            if self.agent_package_runtime
            else 0
        )
        if self.evolution_runtime is not None:
            cancelled += self.evolution_runtime.cancel_active_requests(reason=reason, request_id=target_request_id)
        if self.create_agent_runtime is not None:
            cancelled += self.create_agent_runtime.cancel_active_requests(reason=reason, request_id=target_request_id)
        self.pending_agent_package_run = None
        self.pending_evolution_run = None
        if self.pending_create_agent_run is not None:
            cancelled += 1
            self.pending_create_agent_run = None
        self.emit(
            event(
                "debug_patch",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
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
        sync_system_chat_session: bool = True,
    ) -> RuntimeStreamConsumeResult:
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
                    if frontend_mode == "chat" and sync_system_chat_session:
                        self._remember_system_chat_agent_session_id(agent_session_id)
                if item.event_type == "run_completed" and frontend_mode == "chat" and sync_system_chat_session:
                    self._sync_system_chat_session_summary(item)
                if item.event_type in INTERRUPT_TERMINAL_EVENT_TYPES:
                    if frontend_mode == "chat" and sync_system_chat_session:
                        self._finish_system_chat_turn(
                            request_id=item.request_id,
                            final_answer=visible_output.content,
                            reasoning_content=visible_output.reasoning_content,
                            status="interrupted",
                        )
                    session_id = str(agent_session_id or (run.session or {}).get("session_id") or "")
                    if not session_id:
                        raise RuntimeError("agent package interrupt missing session_id")
                    self.pending_agent_package_run = PendingAgentPackageRun(
                        package_id=package_id,
                        session_id=session_id,
                        normalizer=normalizer,
                        interrupt_id=_interrupt_id_from_event(item),
                        interrupt_event_id=item.event_id,
                    )
                self.emit(
                    _frontend_scoped_agent_event(
                        item,
                        mode=frontend_mode,
                        session_id=frontend_session_id,
                        package_id=package_id,
                    )
                )
                if item.event_type in INTERRUPT_TERMINAL_EVENT_TYPES or item.event_type in RUN_TERMINAL_EVENT_TYPES:
                    if (
                        item.event_type in RUN_TERMINAL_EVENT_TYPES
                        and item.event_type != "run_completed"
                        and frontend_mode == "chat"
                        and sync_system_chat_session
                    ):
                        self._finish_system_chat_turn(
                            request_id=item.request_id,
                            final_answer=visible_output.content,
                            reasoning_content=visible_output.reasoning_content,
                            status=runtime_stream_status(item),
                        )
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
                self.pending_agent_package_run = PendingAgentPackageRun(
                    package_id=package_id,
                    session_id=session_id,
                    normalizer=normalizer,
                    interrupt_id=_interrupt_id_from_payload(interrupt_payload),
                )
                payload = json_safe(interrupt_payload)
                if isinstance(payload, dict):
                    payload = {**payload, "package_id": package_id}
                normalizer.emit_interrupt(payload)
                return RuntimeStreamConsumeResult(status="interrupted")
            if stream_mode == "runtime_final":
                final_state = chunk
                continue
            normalizer.emit_stream_item(stream_mode, chunk, updates_payload_key="agent_package_update")
        if terminal_event is not None:
            return RuntimeStreamConsumeResult(status=runtime_stream_status(terminal_event), terminal_event=terminal_event)
        if final_state is None:
            raise RuntimeError("agent package runtime did not produce a final state")
        if not runtime_completed(final_state):
            message = runtime_error_message(final_state, command="agent package runtime")
            normalizer.complete_open_model_streams(reason="run_failed")
            normalizer.emit_run_failed(RuntimeError(message))
            return RuntimeStreamConsumeResult(status="failed", message=message)
        normalizer.complete_visible_assistant_output_from_state(final_state, reason="run_completed")
        normalizer.emit_run_completed(
            {
                "status": final_state.execution.finish_status,
                "package_id": package_id,
                "agent_id": run.package.assembly_spec.agent.id,
                "agent_session": run.session,
            }
        )
        return RuntimeStreamConsumeResult(status="completed")

    def _run_chat(self, command: FactoryFrontendCommand, message: str) -> None:
        redacted_message = redact_attachment_markers(message)
        display_user_input = str(command.payload.get("display_user_input") or "").strip() or redacted_message
        agent_session_id = self._planned_system_chat_agent_session_id()
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=self._session_id(),
            mode="chat",
            graph_id="factory_chat_package",
            producer_type="factory_runtime",
        )
        try:
            self._commit_system_chat_request(
                display_user_input,
                request_id=command.request_id,
                attachments=transcript_attachment_views(command.payload.get("attachments")),
            )
            run = self.agent_package_runtime.stream(
                SYSTEM_CHAT_PACKAGE_ID,
                user_input=message,
                display_user_input=display_user_input,
                session_id=agent_session_id,
                request_id=command.request_id,
                user_config=_runtime_user_config(command),
                attachments=command.payload.get("attachments"),
            )
            self._consume_agent_package_stream(
                package_id=SYSTEM_CHAT_PACKAGE_ID,
                run=run,
                normalizer=normalizer,
                frontend_mode="chat",
                frontend_session_id=self._session_id(),
            )
        except AttachmentImportError as exc:
            _emit_attachment_import_failed(normalizer, exc)
            self._finish_system_chat_turn(request_id=command.request_id, final_answer=None, status="failed")
        except Exception as exc:
            normalizer.emit_run_failed(exc)
            self._finish_system_chat_turn(request_id=command.request_id, final_answer=None, status="failed")

    def _run_create_agent(self, command: FactoryFrontendCommand, message: str) -> None:
        redacted_message = redact_attachment_markers(message)
        agent_session_id = self._planned_host_create_agent_session_id()
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=self._session_id(),
            mode="create_agent",
            graph_id="create_agent_react",
            producer_type="factory_runtime",
        )
        try:
            self._commit_host_create_agent_request(
                redacted_message,
                session_id=agent_session_id,
                request_id=command.request_id,
                attachments=transcript_attachment_views(command.payload.get("attachments")),
            )
            run = self.create_agent_runtime.stream(
                user_input=message,
                session_id=agent_session_id,
                request_id=command.request_id,
                user_config=_runtime_user_config(command),
                attachments=command.payload.get("attachments"),
            )
            self._consume_create_agent_stream(run=run)
        except AttachmentImportError as exc:
            _emit_attachment_import_failed(normalizer, exc)
            self._finish_host_create_agent_turn(request_id=command.request_id, final_answer=None, status="failed")
        except Exception as exc:
            normalizer.emit_run_failed(exc)
            self._finish_host_create_agent_turn(request_id=command.request_id, final_answer=None, status="failed")

    def _sync_system_chat_session_summary(self, item: FactoryFrontendEvent) -> None:
        if self.session_record is None:
            return
        agent_session = item.payload.get("agent_session") if isinstance(item.payload, dict) else None
        if isinstance(agent_session, dict):
            self.session_record.chat_agent_package_session_id = str(
                agent_session.get("session_id") or self.session_record.chat_agent_package_session_id or ""
            ) or None
            try:
                self.session_record.chat_turn_count = int(
                    agent_session.get("turn_count")
                    or self.session_record.chat_turn_count
                )
            except (TypeError, ValueError):
                pass
            turns = agent_session.get("turns")
            if isinstance(turns, list):
                self.session_record = self.session_manager.replace_turns_from_agent_session(
                    self.session_record.session_id,
                    "chat",
                    [turn for turn in turns if isinstance(turn, dict)],
                )
                return
        self.session_manager.save(self.session_record)

    def _planned_system_chat_agent_session_id(self) -> str | None:
        return self.session_record.chat_agent_package_session_id if self.session_record is not None else None

    def _commit_system_chat_request(
        self,
        first_user_input: str,
        *,
        request_id: str | None = None,
        attachments: Any = None,
    ) -> None:
        self._remember_factory_first_user_input(first_user_input)
        self.session_record = self.session_manager.start_turn(
            self.session_record.session_id,
            "chat",
            request_id=request_id,
            user_input=first_user_input,
            attachments=attachments,
        )

    def _finish_system_chat_turn(
        self,
        *,
        request_id: str | None,
        final_answer: str | None,
        status: str,
        reasoning_content: str | None = None,
        tool_activities: list[dict[str, Any]] | None = None,
        trace_ref: dict[str, str] | None = None,
    ) -> None:
        if self.session_record is None:
            return
        self.session_record = self.session_manager.finish_turn(
            self.session_record.session_id,
            "chat",
            request_id=request_id,
            final_answer=final_answer,
            reasoning_content=reasoning_content,
            status=status,
            tool_activities=tool_activities,
            trace_ref=trace_ref,
        )

    def _remember_system_chat_agent_session_id(self, session_id: str) -> None:
        if self.session_record is None:
            self.start_session(FactoryFrontendCommand(type="start_session"))
        if self.session_record.chat_agent_package_session_id != session_id:
            self.session_record.chat_agent_package_session_id = session_id
            self.session_manager.save(self.session_record)

    def _planned_host_create_agent_session_id(self) -> str:
        if self.session_record is not None and self.session_record.create_agent_session_id:
            return self.session_record.create_agent_session_id
        return uuid4().hex

    def _commit_host_create_agent_request(
        self,
        first_user_input: str,
        *,
        session_id: str,
        request_id: str | None = None,
        attachments: Any = None,
    ) -> None:
        self._remember_factory_first_user_input(first_user_input)
        if self.session_record.create_agent_session_id != session_id:
            self.session_record.create_agent_session_id = session_id
        self.session_manager.save(self.session_record)
        self.session_record = self.session_manager.start_turn(
            self.session_record.session_id,
            "create_agent",
            request_id=request_id,
            user_input=first_user_input,
            attachments=attachments,
        )

    def _remember_factory_first_user_input(self, first_user_input: str) -> None:
        if self.session_record is None:
            self.start_session(FactoryFrontendCommand(type="start_session"))
        self.session_record = self.session_manager.remember_first_user_input(
            self.session_record.session_id,
            first_user_input,
        )

    def _commit_evolution_request(
        self,
        first_user_input: str,
        *,
        package_id: str,
        request_id: str | None = None,
        attachments: Any = None,
    ) -> None:
        self._remember_factory_first_user_input(first_user_input)
        self.evolution_package_id = package_id
        self.session_record = self.session_manager.set_evolution_package(
            self.session_record.session_id,
            package_id,
        )
        self.session_record = self.session_manager.start_turn(
            self.session_record.session_id,
            "evolve_agent",
            request_id=request_id,
            user_input=first_user_input,
            attachments=attachments,
        )

    def _finish_evolution_turn(
        self,
        *,
        request_id: str | None,
        final_answer: str | None,
        status: str,
        reasoning_content: str | None = None,
    ) -> None:
        if self.session_record is None:
            return
        self.session_record = self.session_manager.finish_turn(
            self.session_record.session_id,
            "evolve_agent",
            request_id=request_id,
            final_answer=final_answer,
            reasoning_content=reasoning_content,
            status=status,
        )

    def _consume_create_agent_stream(self, *, run: Any) -> RuntimeStreamConsumeResult:
        terminal_event: FactoryFrontendEvent | None = None
        visible_output = VisibleAssistantOutputAccumulator()
        for stream_mode, chunk in run.events:
            if terminal_event is not None:
                continue
            if stream_mode != "frontend_event":
                raise RuntimeError(f"create-agent runtime emitted non-frontend event stream: {stream_mode}")
            item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
            visible_output.accept(item)
            if item.event_type in INTERRUPT_TERMINAL_EVENT_TYPES:
                self._finish_host_create_agent_turn(
                    request_id=item.request_id,
                    final_answer=visible_output.content,
                    reasoning_content=visible_output.reasoning_content,
                    status="interrupted",
                )
                self.pending_create_agent_run = PendingCreateAgentRun(
                    session_id=run.session_id,
                    request_id=item.request_id,
                    interrupt_id=_interrupt_id_from_event(item),
                    interrupt_event_id=item.event_id,
                )
                self.emit(_frontend_scoped_agent_event(item, mode="create_agent", session_id=self._session_id()))
                terminal_event = item
                continue
            self.emit(_frontend_scoped_agent_event(item, mode="create_agent", session_id=self._session_id()))
            if item.event_type in RUN_TERMINAL_EVENT_TYPES:
                self._finish_host_create_agent_turn(
                    request_id=item.request_id,
                    final_answer=visible_output.content,
                    reasoning_content=visible_output.reasoning_content,
                    status=runtime_stream_status(item),
                )
                terminal_event = item
        if terminal_event is not None:
            return RuntimeStreamConsumeResult(status=runtime_stream_status(terminal_event), terminal_event=terminal_event)
        raise RuntimeError("create-agent runtime stream ended without a terminal event")

    def _finish_host_create_agent_turn(
        self,
        *,
        request_id: str | None,
        final_answer: str | None,
        status: str,
        reasoning_content: str | None = None,
    ) -> None:
        if self.session_record is None:
            return
        self.session_record = self.session_manager.finish_turn(
            self.session_record.session_id,
            "create_agent",
            request_id=request_id,
            final_answer=final_answer,
            reasoning_content=reasoning_content,
            status=status,
        )


def _frontend_scoped_agent_event(
    item: FactoryFrontendEvent,
    *,
    mode: FactoryMode | None,
    session_id: str | None,
    package_id: str | None = None,
) -> FactoryFrontendEvent:
    updates: dict[str, Any] = {}
    if mode is not None:
        updates["mode"] = mode
    if session_id is not None:
        updates["session_id"] = session_id
    if package_id is not None:
        updates["payload"] = {
            **(item.payload if isinstance(item.payload, dict) else {}),
            "package_id": package_id,
        }
    return item.model_copy(update=updates) if updates else item


def _runtime_user_config(command: FactoryFrontendCommand) -> dict[str, Any]:
    payload = command.payload if isinstance(command.payload, dict) else {}
    user_config = payload.get("user_config")
    return dict(user_config) if isinstance(user_config, dict) else {}


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
