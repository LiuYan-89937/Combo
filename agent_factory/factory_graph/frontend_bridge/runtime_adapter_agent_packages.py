from __future__ import annotations

from typing import Any
from uuid import uuid4

from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer, json_safe
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, FactoryFrontendEvent, FactoryMode, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import extract_interrupt_payload
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import (
    PendingAgentPackageRun,
    PendingCreateAgentRun,
    SYSTEM_CHAT_PACKAGE_ID,
)
from agent_factory.runtime_protocol.completion import runtime_completed, runtime_error_message


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

    def run_agent_package(self, command: FactoryFrontendCommand) -> None:
        package_id = str(command.payload.get("package_id") or "").strip()
        message = str(command.payload.get("message") or command.message or "").strip()
        session_id = str(command.payload.get("session_id") or "").strip() or None
        if not package_id:
            self._emit_error(command, "run_agent_package requires package_id")
            return
        if not message:
            self._emit_error(command, "run_agent_package requires message")
            return
        if self.pending_agent_package_run is not None:
            self._emit_error(command, "cannot run an agent package while an interrupt is pending")
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
                session_id=session_id,
                request_id=command.request_id,
            )
            self._consume_agent_package_stream(package_id=package_id, run=run, normalizer=normalizer)
        except Exception as exc:
            normalizer.emit_run_failed(exc)

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
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=self._session_id(),
            mode="create_agent",
            graph_id="create_agent_react",
            producer_type="factory_runtime",
        )
        try:
            run = self.create_agent_runtime.resume_stream(
                session_id=pending.session_id,
                resume_payload=command.payload,
                request_id=command.request_id,
            )
            self._consume_create_agent_stream(run=run)
        except Exception as exc:
            normalizer.emit_run_failed(exc)

    def cancel_runtime_request(self, command: FactoryFrontendCommand) -> None:
        reason = str(command.payload.get("reason") or "user_cancelled")
        cancelled = self.agent_package_runtime.cancel_active_requests(reason=reason) if self.agent_package_runtime else 0
        self.pending_agent_package_run = None
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
                payload={"source": "runtime_request_cancel", "reason": reason, "cancelled_requests": cancelled},
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
    ) -> None:
        final_state = None
        terminal_event_seen = False
        for stream_mode, chunk in run.events:
            if stream_mode == "frontend_event":
                item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
                agent_session_id = item.session_id
                if agent_session_id:
                    run.session["session_id"] = agent_session_id
                if item.event_type in {"run_completed", "run_failed"}:
                    terminal_event_seen = True
                if item.event_type == "run_completed" and frontend_mode == "chat":
                    self._sync_system_chat_session_summary(item)
                if item.event_type in {"tool_approval_requested", "interrupt_requested"}:
                    session_id = str(agent_session_id or (run.session or {}).get("session_id") or "")
                    if not session_id:
                        raise RuntimeError("agent package interrupt missing session_id")
                    self.pending_agent_package_run = PendingAgentPackageRun(
                        package_id=package_id,
                        session_id=session_id,
                        normalizer=normalizer,
                        interrupt_id=_interrupt_id_from_event(item),
                    )
                self.emit(_frontend_scoped_agent_event(item, mode=frontend_mode, session_id=frontend_session_id))
                if item.event_type in {"tool_approval_requested", "interrupt_requested"}:
                    return
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
                normalizer.emit_interrupt(json_safe(interrupt_payload))
                return
            if stream_mode == "runtime_final":
                final_state = chunk
                continue
            normalizer.emit_stream_item(stream_mode, chunk, updates_payload_key="agent_package_update")
        if terminal_event_seen:
            return
        if final_state is None:
            raise RuntimeError("agent package runtime did not produce a final state")
        if not runtime_completed(final_state):
            normalizer.complete_open_model_streams(reason="run_failed")
            normalizer.emit_run_failed(RuntimeError(runtime_error_message(final_state, command="agent package runtime")))
            return
        normalizer.complete_open_model_streams(reason="run_completed")
        normalizer.emit_run_completed(
            {
                "status": final_state.execution.finish_status,
                "package_id": package_id,
                "agent_id": run.package.assembly_spec.agent.id,
                "agent_session": run.session,
            }
        )

    def _run_chat(self, command: FactoryFrontendCommand, message: str) -> None:
        agent_session_id = self._ensure_system_chat_agent_session(message)
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=self._session_id(),
            mode="chat",
            graph_id="factory_chat_package",
            producer_type="factory_runtime",
        )
        try:
            run = self.agent_package_runtime.stream(
                SYSTEM_CHAT_PACKAGE_ID,
                user_input=message,
                session_id=agent_session_id,
                request_id=command.request_id,
            )
            self._consume_agent_package_stream(
                package_id=SYSTEM_CHAT_PACKAGE_ID,
                run=run,
                normalizer=normalizer,
                frontend_mode="chat",
                frontend_session_id=self._session_id(),
            )
        except Exception as exc:
            normalizer.emit_run_failed(exc)

    def _run_create_agent(self, command: FactoryFrontendCommand, message: str) -> None:
        agent_session_id = self._ensure_host_create_agent_session(message)
        normalizer = RuntimeEventNormalizer(
            emit=self.emit,
            request_id=command.request_id,
            session_id=self._session_id(),
            mode="create_agent",
            graph_id="create_agent_react",
            producer_type="factory_runtime",
        )
        try:
            run = self.create_agent_runtime.stream(
                user_input=message,
                session_id=agent_session_id,
                request_id=command.request_id,
            )
            self._consume_create_agent_stream(run=run)
        except Exception as exc:
            normalizer.emit_run_failed(exc)

    def _sync_system_chat_session_summary(self, item: FactoryFrontendEvent) -> None:
        if self.session_record is None:
            return
        agent_session = item.payload.get("agent_session") if isinstance(item.payload, dict) else None
        if isinstance(agent_session, dict):
            self.session_record.chat_agent_package_session_id = str(
                agent_session.get("session_id") or self.session_record.chat_agent_package_session_id or ""
            ) or None
            try:
                self.session_record.chat_turn_count = int(agent_session.get("turn_count") or self.session_record.chat_turn_count)
            except (TypeError, ValueError):
                pass
        self.session_manager.save(self.session_record)

    def _ensure_system_chat_agent_session(self, first_user_input: str) -> str:
        if self.session_record is None:
            self.start_session(FactoryFrontendCommand(type="start_session"))
        self.session_record = self.session_manager.remember_first_user_input(
            self.session_record.session_id,
            first_user_input,
        )
        agent_session = self.agent_package_runtime.ensure_session(
            SYSTEM_CHAT_PACKAGE_ID,
            session_id=self.session_record.chat_agent_package_session_id,
            first_user_input=first_user_input,
        )
        agent_session_id = str(agent_session.get("session_id") or "")
        if agent_session_id != self.session_record.chat_agent_package_session_id:
            self.session_record.chat_agent_package_session_id = agent_session_id
            self.session_manager.save(self.session_record)
        return agent_session_id

    def _ensure_host_create_agent_session(self, first_user_input: str) -> str:
        if self.session_record is None:
            self.start_session(FactoryFrontendCommand(type="start_session"))
        self.session_record = self.session_manager.remember_first_user_input(
            self.session_record.session_id,
            first_user_input,
        )
        if not self.session_record.create_agent_session_id:
            self.session_record.create_agent_session_id = uuid4().hex
        self.session_record.create_agent_turn_count += 1
        self.session_manager.save(self.session_record)
        return self.session_record.create_agent_session_id

    def _consume_create_agent_stream(self, *, run: Any) -> None:
        for stream_mode, chunk in run.events:
            if stream_mode != "frontend_event":
                raise RuntimeError(f"create-agent runtime emitted non-frontend event stream: {stream_mode}")
            item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
            if item.event_type in {"interrupt_requested", "tool_approval_requested"}:
                self.pending_create_agent_run = PendingCreateAgentRun(session_id=run.session_id)
            self.emit(_frontend_scoped_agent_event(item, mode="create_agent", session_id=self._session_id()))


def _frontend_scoped_agent_event(
    item: FactoryFrontendEvent,
    *,
    mode: FactoryMode | None,
    session_id: str | None,
) -> FactoryFrontendEvent:
    updates: dict[str, Any] = {}
    if mode is not None:
        updates["mode"] = mode
    if session_id is not None:
        updates["session_id"] = session_id
    return item.model_copy(update=updates) if updates else item


def _interrupt_id_from_event(item: FactoryFrontendEvent) -> str | None:
    return _interrupt_id_from_payload(item.payload if isinstance(item.payload, dict) else {})


def _interrupt_id_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    interrupt_id = str(payload.get("interrupt_id") or "").strip()
    return interrupt_id or None
