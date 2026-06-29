from __future__ import annotations

from dataclasses import asdict

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import session_payload
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import (
    FactoryBridgeOptions,
    SYSTEM_CHAT_PACKAGE_ID,
)


class RuntimeSessionCommandMixin:
    def start_session(self, command: FactoryFrontendCommand) -> None:
        if command.session_id:
            self.session_record = self.session_manager.load(command.session_id)
            session_event_type = "session_switched"
        elif command.resume_latest:
            self.session_record = self.session_manager.latest() or self.session_manager.create()
            session_event_type = "session_switched" if self.session_record else "session_started"
        else:
            self.session_record = self.session_manager.create()
            session_event_type = "session_started"
        self.mode = self.session_record.current_mode
        self._emit_session_event(command.request_id, session_event_type=session_event_type)

    def list_sessions(self, command: FactoryFrontendCommand) -> None:
        self.emit(
            event(
                "sessions_listed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={"sessions": [session_payload(item) for item in self.session_manager.list_sessions()]},
            )
        )

    def switch_session(self, command: FactoryFrontendCommand) -> None:
        if not command.session_id:
            self._emit_error(command, "switch_session requires session_id")
            return
        self.session_record = self.session_manager.load(command.session_id)
        self.mode = self.session_record.current_mode
        self.pending_agent_package_run = None
        self._emit_session_event(command.request_id, session_event_type="session_switched")

    def new_session(self, command: FactoryFrontendCommand) -> None:
        self.session_record = self.session_manager.create()
        self.mode = None
        self.pending_agent_package_run = None
        self._emit_session_event(command.request_id, session_event_type="session_started")

    def set_mode(self, command: FactoryFrontendCommand) -> None:
        self._ensure_session(command)
        if command.mode == "agent_package":
            self._emit_error(command, "use list_agent_packages/select_agent_package to enter agent package mode")
            return
        self.mode = command.mode
        self.session_record = self.session_manager.set_mode(self.session_record.session_id, self.mode)
        self.emit(
            event(
                "mode_changed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={
                    "mode": self.mode,
                    **({"package_id": SYSTEM_CHAT_PACKAGE_ID} if self.mode == "chat" else {}),
                    **({"graph_id": "create_agent_react"} if self.mode == "create_agent" else {}),
                },
            )
        )

    def set_options(self, command: FactoryFrontendCommand) -> None:
        self.options = FactoryBridgeOptions(
            show_state=bool(command.options.get("show_state", self.options.show_state)),
            show_messages=bool(command.options.get("show_messages", self.options.show_messages)),
        )
        self.emit(
            event(
                "runtime_options_changed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={"options": asdict(self.options)},
            )
        )

    def send_message(self, command: FactoryFrontendCommand) -> None:
        self._ensure_session(command)
        if self.mode not in {"chat", "create_agent", "evolve_agent"}:
            self._emit_error(command, "enter /chat, /create-agent, or /evolve-agent before sending messages")
            return
        message = (command.message or "").strip()
        if not message:
            self._emit_error(command, "send_message requires message")
            return
        if self.pending_agent_package_run is not None or self.pending_create_agent_run is not None:
            self._emit_error(command, "cannot send a new message while an interrupt is pending")
            return
        if self.mode == "chat":
            self._run_chat(command, message)
        elif self.mode == "create_agent":
            self._run_create_agent(command, message)
        else:
            self._run_evolve_agent(command, message)

    def resume_interrupt(self, command: FactoryFrontendCommand) -> None:
        if self.pending_create_agent_run is not None:
            self._resume_create_agent_interrupt(command)
            return
        if self.pending_agent_package_run is None:
            self._emit_error(command, "no pending interrupt to resume")
            return
        self._resume_agent_package_interrupt(command)

    def _emit_session_event(self, request_id: str | None, *, session_event_type: str = "session_switched") -> None:
        self.emit(
            event(
                session_event_type,
                request_id=request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={"session": session_payload(self.session_record)},
            )
        )

    def _emit_error(self, command: FactoryFrontendCommand, message: str) -> None:
        self.emit(
            event(
                "error",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                message=message,
            )
        )

    def _ensure_session(self, command: FactoryFrontendCommand) -> None:
        if self.session_record is None:
            self.start_session(FactoryFrontendCommand(type="start_session", request_id=command.request_id))

    def _session_id(self) -> str | None:
        if self.session_record is None:
            return None
        return str(self.session_record.session_id)

    def checkpointer_payload(self) -> dict[str, object]:
        return {
            "backend": "system_package",
            "persistent": True,
            "path": None,
        }
