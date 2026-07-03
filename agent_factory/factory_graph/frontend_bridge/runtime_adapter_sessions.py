from __future__ import annotations

from dataclasses import asdict
from typing import Any

from agent_factory.create_agent.validation_state import package_fingerprint
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import session_payload
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import (
    PendingCreateAgentRun,
    SYSTEM_CHAT_PACKAGE_ID,
)
from agent_factory.runtime_attachments import has_attachment_payload, transcript_attachment_views


MESSAGE_MODES = {"chat", "create_agent", "evolve_agent"}
SESSION_MODES = {"chat", "create_agent", "evolve_agent"}


class RuntimeSessionCommandMixin:
    def start_session(self, command: FactoryFrontendCommand) -> None:
        requested_mode = _session_mode(command.mode)
        requested_evolution_package_id = _command_evolution_package_id(command, requested_mode)
        if command.session_id:
            previous_record = self.session_record
            previous_mode = self.mode
            self.session_record = self.session_manager.load(command.session_id)
            self.mode = requested_mode or self.session_record.current_mode
            if not self._session_source_available(self.session_record, self.mode):
                self.session_record = previous_record
                self.mode = previous_mode
                self._emit_missing_session_source(command, requested_mode or "chat")
                return
            if requested_mode is not None and requested_mode != self.session_record.current_mode:
                self.session_record = self.session_manager.set_mode(self.session_record.session_id, requested_mode)
            if requested_evolution_package_id:
                self.session_record = self.session_manager.set_evolution_package(
                    self.session_record.session_id,
                    requested_evolution_package_id,
                )
            session_event_type = "session_switched"
        elif command.resume_latest:
            existing = self._latest_session_for_start(requested_mode, requested_evolution_package_id)
            self.session_record = existing or self.session_manager.create(mode=requested_mode)
            self.mode = requested_mode or self.session_record.current_mode
            if requested_evolution_package_id:
                self.session_record = self.session_manager.set_evolution_package(
                    self.session_record.session_id,
                    requested_evolution_package_id,
                )
            session_event_type = "session_switched" if existing else "session_started"
        else:
            self.session_record = self.session_manager.create(mode=requested_mode)
            self.mode = requested_mode
            if requested_evolution_package_id:
                self.session_record = self.session_manager.set_evolution_package(
                    self.session_record.session_id,
                    requested_evolution_package_id,
                )
            session_event_type = "session_started"
        self._restore_session_mode_context()
        self._emit_session_event(command.request_id, session_event_type=session_event_type)

    def list_sessions(self, command: FactoryFrontendCommand) -> None:
        self.emit(
            event(
                "sessions_listed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={"sessions": self._session_payloads_for_client()},
            )
        )

    def switch_session(self, command: FactoryFrontendCommand) -> None:
        if not command.session_id:
            self._emit_error(command, "switch_session requires session_id")
            return
        requested_mode = _session_mode(command.mode)
        previous_record = self.session_record
        previous_mode = self.mode
        self.session_record = self.session_manager.load(command.session_id)
        self.mode = requested_mode or self.session_record.current_mode
        if not self._session_source_available(self.session_record, self.mode):
            self.session_record = previous_record
            self.mode = previous_mode
            self._emit_missing_session_source(command, requested_mode or "chat")
            return
        if requested_mode is not None and requested_mode != self.session_record.current_mode:
            self.session_record = self.session_manager.set_mode(self.session_record.session_id, requested_mode)
        self._restore_session_mode_context()
        self._emit_session_event(command.request_id, session_event_type="session_switched")

    def new_session(self, command: FactoryFrontendCommand) -> None:
        self.mode = _session_mode(command.mode)
        self.session_record = self.session_manager.create(mode=self.mode)
        requested_evolution_package_id = _command_evolution_package_id(command, self.mode)
        if requested_evolution_package_id:
            self.session_record = self.session_manager.set_evolution_package(
                self.session_record.session_id,
                requested_evolution_package_id,
            )
        self._restore_session_mode_context()
        self._emit_session_event(command.request_id, session_event_type="session_started")

    def delete_session(self, command: FactoryFrontendCommand) -> None:
        session_id = str(command.session_id or command.payload.get("session_id") or "").strip()
        if not session_id:
            self._emit_error(command, "delete_session requires session_id")
            return
        record = self.session_manager.load(session_id)
        delete_mode = (
            _session_mode(command.mode)
            or _session_mode(str(command.payload.get("mode") or ""))
            or _session_mode(self.mode)
            or record.current_mode
        )
        linked_artifacts = self._delete_linked_session_artifacts(record, mode=delete_mode)
        affected_session_ids = self._delete_or_detach_logical_session(record, mode=delete_mode)
        deleted_active = (
            self.session_record is not None
            and self.session_record.session_id in affected_session_ids
            and delete_mode == self.mode
        )
        if deleted_active:
            self.session_record = None
            self.pending_create_agent_run = None
            self.pending_evolution_run = None
            self.pending_agent_package_run = None
        self.emit(
            event(
                "session_deleted",
                request_id=command.request_id,
                session_id=None if deleted_active else self._session_id(),
                mode=self.mode,
                payload={
                    "session_id": record.session_id,
                    "session_ids": sorted(affected_session_ids),
                    "deleted": True,
                    "deleted_active": deleted_active,
                    "linked_artifacts": linked_artifacts,
                    "sessions": self._session_payloads_for_client(),
                },
            )
        )

    def set_mode(self, command: FactoryFrontendCommand) -> None:
        self._ensure_session(command)
        if command.mode == "agent_package":
            self._emit_error(command, "use list_agent_packages/select_agent_package to enter agent package mode")
            return
        self._apply_mode(command, command.mode)

    def send_message(self, command: FactoryFrontendCommand) -> None:
        self._ensure_session(command)
        if command.mode in MESSAGE_MODES and command.mode != self.mode:
            self._apply_mode(command, command.mode)
        if self.mode not in {"chat", "create_agent", "evolve_agent"}:
            self._emit_error(command, "enter /chat, /create-agent, or /evolve-agent before sending messages")
            return
        message = (command.message or "").strip()
        if not message and not has_attachment_payload(command.payload.get("attachments")):
            self._emit_error(command, "send_message requires message")
            return
        if (
            self.pending_agent_package_run is not None
            or self.pending_create_agent_run is not None
            or self.pending_evolution_run is not None
        ):
            self._emit_error(command, "cannot send a new message while an interrupt is pending")
            return
        if self.mode == "chat":
            self._run_chat(command, message)
        elif self.mode == "create_agent":
            self._run_create_agent(command, message)
        else:
            self._run_evolve_agent(command, message)

    def _apply_mode(self, command: FactoryFrontendCommand, mode: str | None) -> None:
        if self.session_record is None:
            self._ensure_session(command)
        self.mode = mode
        self.session_record = self.session_manager.set_mode(self.session_record.session_id, self.mode)
        self._restore_session_mode_context()
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

    def resume_interrupt(self, command: FactoryFrontendCommand) -> None:
        target = _interrupt_resume_target(command.payload)
        if self.pending_create_agent_run is not None and _pending_create_agent_matches(self.pending_create_agent_run, target):
            self._resume_create_agent_interrupt(command)
            return
        if self.pending_evolution_run is not None and _pending_evolution_matches(self.pending_evolution_run, target):
            self._resume_evolution_interrupt(command)
            return
        if self.pending_agent_package_run is not None and _pending_agent_package_matches(self.pending_agent_package_run, target):
            self._resume_agent_package_interrupt(command)
            return
        if self._recover_create_agent_publish_confirmation(command):
            return
        if target.explicit:
            self._emit_error(command, "no matching pending interrupt to resume")
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
                payload={"session": self._session_payload()},
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

    def _delete_linked_session_artifacts(self, record, *, mode: str | None = None) -> dict[str, object]:
        artifacts: dict[str, object] = {}
        chat_session_id = str(getattr(record, "chat_agent_package_session_id", "") or "").strip()
        if (mode in {None, "chat"}) and chat_session_id and self.agent_package_runtime is not None:
            artifacts["chat"] = self.agent_package_runtime.delete_session(SYSTEM_CHAT_PACKAGE_ID, chat_session_id)

        create_session_id = str(getattr(record, "create_agent_session_id", "") or "").strip()
        if (mode in {None, "create_agent"}) and create_session_id and self.create_agent_runtime is not None:
            artifacts["create_agent"] = self.create_agent_runtime.delete_session_artifacts(create_session_id)

        evolve_package_id = str(getattr(record, "evolve_agent_package_id", "") or "").strip()
        if (mode in {None, "evolve_agent"}) and evolve_package_id and self.evolution_runtime is not None:
            artifacts["evolve_agent"] = self.evolution_runtime.delete_session_artifacts(
                package_id=evolve_package_id,
                session_id=record.session_id,
                request_ids=_turn_request_ids(getattr(record, "evolve_agent_turns", [])),
            )
        return artifacts

    def _recover_create_agent_publish_confirmation(self, command: FactoryFrontendCommand) -> bool:
        if str(command.payload.get("type") or "").strip() != "create_agent_publish_confirmation":
            return False
        payload_mode = str(command.payload.get("mode") or self.mode or "").strip()
        if payload_mode != "create_agent":
            return False
        if self.session_record is None or not self.session_record.create_agent_session_id:
            return False
        frontend_session_id = str(command.payload.get("frontend_session_id") or "").strip()
        if frontend_session_id and frontend_session_id != str(self.session_record.session_id):
            return False
        agent_session_id = str(self.session_record.create_agent_session_id)
        workspace = CreateAgentWorkspace.for_session(agent_session_id)
        if not _publish_confirmation_ready(workspace):
            return False
        self.pending_create_agent_run = PendingCreateAgentRun(
            session_id=agent_session_id,
            request_id=str(command.payload.get("pending_request_id") or command.request_id or "").strip() or None,
            interrupt_id=str(command.payload.get("interrupt_id") or "").strip() or None,
            interrupt_event_id=str(command.payload.get("interrupt_event_id") or "").strip() or None,
        )
        self._resume_create_agent_interrupt(command)
        return True

    def _ensure_session(self, command: FactoryFrontendCommand) -> None:
        if self.session_record is None:
            self.start_session(FactoryFrontendCommand(type="start_session", request_id=command.request_id))

    def _latest_session_for_start(
        self,
        requested_mode: str | None,
        requested_evolution_package_id: str | None,
    ):
        if requested_evolution_package_id:
            return self.session_manager.latest_evolution_for_package(requested_evolution_package_id)
        if requested_mode == "chat":
            for record in self._client_session_records():
                if _client_record_matches_mode(record, "chat"):
                    return record
            return None
        if requested_mode is not None:
            return self.session_manager.latest(mode=requested_mode)
        return self.session_manager.latest()

    def _restore_session_mode_context(self) -> None:
        if self.session_record is None:
            return
        if self.mode == "evolve_agent":
            self.evolution_package_id = str(getattr(self.session_record, "evolve_agent_package_id", "") or "").strip() or None
            return
        if self.mode != "agent_package":
            self.evolution_package_id = None

    def _session_id(self) -> str | None:
        if self.session_record is None:
            return None
        return str(self.session_record.session_id)

    def _session_payload(self) -> dict[str, object]:
        payload = session_payload(self.session_record, snapshot_mode=self.mode)
        snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
        messages = list(snapshot.get("messages") or []) if isinstance(snapshot, dict) else []
        linked_agent_session = self._linked_agent_session_payload()
        if self.mode == "chat" and linked_agent_session is not None:
            messages = _messages_from_agent_session(linked_agent_session)
            linked_turns = _turns_from_agent_session(linked_agent_session)
            self._sync_factory_turns_from_linked_session(linked_agent_session)
            snapshot = {
                **snapshot,
                "turns": linked_turns,
                "messages": messages,
                "agent_session": linked_agent_session,
            }
        elif not messages and linked_agent_session is not None:
            messages = _messages_from_agent_session(linked_agent_session)
            linked_turns = _turns_from_agent_session(linked_agent_session)
            self._sync_factory_turns_from_linked_session(linked_agent_session)
            snapshot = {
                **snapshot,
                "turns": linked_turns,
                "messages": messages,
                "agent_session": linked_agent_session,
            }
        payload["snapshot"] = snapshot
        return payload

    def _session_payloads_for_client(self) -> list[dict[str, object]]:
        return [session_payload(item) for item in self._client_session_records()]

    def _client_session_records(self) -> list[Any]:
        records = self.session_manager.list_sessions()
        chat_sessions = self._chat_agent_sessions_by_id()
        canonical_chat_records = _canonical_chat_records(records, chat_sessions)
        views: list[Any] = []
        for record in records:
            view = record
            chat_session_id = _chat_agent_session_id(record)
            if chat_session_id:
                chat_session = chat_sessions.get(chat_session_id)
                canonical = canonical_chat_records.get(chat_session_id)
                if chat_session is None or canonical is None or canonical.session_id != record.session_id:
                    view = _without_mode_source(record, "chat")
                else:
                    view = _with_chat_session_summary(record, chat_session)
            if _client_record_has_source(view):
                views.append(view)
        return sorted(views, key=lambda item: item.updated_at, reverse=True)

    def _chat_agent_sessions_by_id(self) -> dict[str, dict[str, Any]]:
        if self.agent_package_runtime is None:
            return {}
        try:
            sessions = self.agent_package_runtime.list_sessions(SYSTEM_CHAT_PACKAGE_ID)
        except Exception:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for item in sessions:
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("session_id") or "").strip()
            if session_id:
                result[session_id] = item
        return result

    def _session_source_available(self, record: Any, mode: str | None) -> bool:
        if mode != "chat":
            return True
        chat_session_id = _chat_agent_session_id(record)
        if not chat_session_id:
            return not _record_has_mode_source(record, "chat")
        if self.agent_package_runtime is None:
            return False
        try:
            return self.agent_package_runtime.session_exists(SYSTEM_CHAT_PACKAGE_ID, chat_session_id)
        except Exception:
            return False

    def _emit_missing_session_source(self, command: FactoryFrontendCommand, mode: str) -> None:
        self._emit_error(command, f"{mode} session source is no longer available")
        self.emit(
            event(
                "sessions_listed",
                request_id=command.request_id,
                session_id=self._session_id(),
                mode=self.mode,
                payload={"sessions": self._session_payloads_for_client()},
            )
        )

    def _delete_or_detach_logical_session(self, record: Any, *, mode: str | None) -> set[str]:
        targets = self._logical_session_records(record, mode=mode)
        affected: set[str] = set()
        for target in targets:
            affected.add(target.session_id)
            updated = _without_mode_source(target, mode)
            if _record_has_any_source(updated):
                self.session_manager.save(updated)
            else:
                self.session_manager.delete(target.session_id)
        return affected

    def _logical_session_records(self, record: Any, *, mode: str | None) -> list[Any]:
        if mode == "chat":
            chat_session_id = _chat_agent_session_id(record)
            if chat_session_id:
                return [
                    item
                    for item in self.session_manager.list_sessions()
                    if _chat_agent_session_id(item) == chat_session_id
                ]
        if mode == "create_agent":
            create_session_id = _create_agent_session_id(record)
            if create_session_id:
                return [
                    item
                    for item in self.session_manager.list_sessions()
                    if _create_agent_session_id(item) == create_session_id
                ]
        return [record]

    def _linked_agent_session_payload(self) -> dict[str, object] | None:
        if self.session_record is None:
            return None
        if self.mode == "chat":
            if self.agent_package_runtime is None or not self.session_record.chat_agent_package_session_id:
                return None
            try:
                return self.agent_package_runtime.load_session(
                    SYSTEM_CHAT_PACKAGE_ID,
                    self.session_record.chat_agent_package_session_id,
                )
            except Exception:
                return None
        if self.mode != "create_agent" or self.create_agent_runtime is None or not self.session_record.create_agent_session_id:
            return None
        try:
            return self.create_agent_runtime.load_session_snapshot(self.session_record.create_agent_session_id)
        except Exception:
            return None

    def _sync_factory_turns_from_linked_session(self, linked_agent_session: dict[str, object]) -> None:
        if self.session_record is None or self.mode not in {"chat", "create_agent"}:
            return
        turns = linked_agent_session.get("turns")
        if not isinstance(turns, list):
            return
        try:
            self.session_record = self.session_manager.replace_turns_from_agent_session(
                self.session_record.session_id,
                self.mode,
                [turn for turn in turns if isinstance(turn, dict)],
            )
        except Exception:
            return

    def checkpointer_payload(self) -> dict[str, object]:
        return {
            "backend": "system_package",
            "persistent": True,
            "path": None,
        }

    def _options_payload(self) -> dict[str, object]:
        return asdict(self.options)


def _messages_from_agent_session(record: dict[str, object]) -> list[dict[str, object]]:
    turns = record.get("turns")
    if not isinstance(turns, list):
        return []
    messages: list[dict[str, object]] = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        created_at = turn.get("created_at")
        updated_at = turn.get("updated_at") or created_at
        turn_index = turn.get("index")
        request_id = turn.get("request_id")
        status = turn.get("status")
        user_input = str(turn.get("user_input") or "").strip()
        if user_input:
            attachments = transcript_attachment_views(turn.get("attachments"))
            messages.append(
                {
                    "role": "user",
                    "content": user_input,
                    **({"attachments": attachments} if attachments else {}),
                    "turn_index": turn_index,
                    "request_id": request_id,
                    "status": status,
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
        final_answer = str(turn.get("final_answer") or "").strip()
        if final_answer:
            reasoning_content = str(turn.get("reasoning_content") or "").strip()
            messages.append(
                {
                    "role": "assistant",
                    "content": final_answer,
                    **({"reasoning_content": reasoning_content} if reasoning_content else {}),
                    "turn_index": turn_index,
                    "request_id": request_id,
                    "status": status,
                    "created_at": updated_at,
                    "updated_at": updated_at,
                }
            )
    return messages


def _turns_from_agent_session(record: dict[str, object]) -> list[dict[str, object]]:
    turns = record.get("turns")
    if not isinstance(turns, list):
        return []
    return [dict(turn) for turn in turns if isinstance(turn, dict)]


def _canonical_chat_records(records: list[Any], chat_sessions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    canonical: dict[str, Any] = {}
    for record in records:
        chat_session_id = _chat_agent_session_id(record)
        if not chat_session_id or chat_session_id not in chat_sessions:
            continue
        existing = canonical.get(chat_session_id)
        if existing is None or _record_order_key(record) > _record_order_key(existing):
            canonical[chat_session_id] = record
    return canonical


def _with_chat_session_summary(record: Any, chat_session: dict[str, Any]) -> Any:
    view = record.model_copy(deep=True)
    view.chat_agent_package_session_id = str(chat_session.get("session_id") or view.chat_agent_package_session_id or "") or None
    try:
        view.chat_turn_count = int(chat_session.get("turn_count") or 0)
    except (TypeError, ValueError):
        pass
    first_user_input = _normalized_optional(chat_session.get("first_user_input"))
    display_title = _normalized_optional(chat_session.get("display_title"))
    if first_user_input and not view.first_user_input:
        view.first_user_input = first_user_input
    if display_title:
        view.display_title = display_title
    elif first_user_input and not view.display_title:
        view.display_title = first_user_input
    updated_at = _normalized_optional(chat_session.get("updated_at"))
    if updated_at:
        view.updated_at = updated_at
    return view


def _without_mode_source(record: Any, mode: str | None) -> Any:
    view = record.model_copy(deep=True)
    if mode in {None, "chat"}:
        view.chat_agent_package_session_id = None
        view.chat_turn_count = 0
        view.chat_turns = []
    if mode in {None, "create_agent"}:
        view.create_agent_session_id = None
        view.create_agent_turn_count = 0
        view.create_agent_turns = []
    if mode in {None, "evolve_agent"}:
        view.evolve_agent_package_id = None
        view.evolve_agent_turn_count = 0
        view.evolve_agent_turns = []
    if mode is None or view.current_mode == mode:
        view.current_mode = _fallback_current_mode(view)
    return view


def _client_record_has_source(record: Any) -> bool:
    return (
        _client_record_matches_mode(record, "chat")
        or _client_record_matches_mode(record, "create_agent")
        or _client_record_matches_mode(record, "evolve_agent")
    )


def _record_has_any_source(record: Any) -> bool:
    return (
        _record_has_mode_source(record, "chat")
        or _record_has_mode_source(record, "create_agent")
        or _record_has_mode_source(record, "evolve_agent")
    )


def _client_record_matches_mode(record: Any, mode: str) -> bool:
    if mode == "chat":
        return bool(_chat_agent_session_id(record))
    return _record_has_mode_source(record, mode)


def _record_has_mode_source(record: Any, mode: str) -> bool:
    if mode == "chat":
        return bool(_chat_agent_session_id(record))
    if mode == "create_agent":
        return (
            bool(_create_agent_session_id(record))
            or int(getattr(record, "create_agent_turn_count", 0) or 0) > 0
            or bool(getattr(record, "create_agent_turns", None))
        )
    if mode == "evolve_agent":
        return (
            bool(_evolve_agent_package_id(record))
            or int(getattr(record, "evolve_agent_turn_count", 0) or 0) > 0
            or bool(getattr(record, "evolve_agent_turns", None))
        )
    return False


def _fallback_current_mode(record: Any) -> str | None:
    for mode in ("chat", "create_agent", "evolve_agent"):
        if _record_has_mode_source(record, mode):
            return mode
    return None


def _chat_agent_session_id(record: Any) -> str:
    return str(getattr(record, "chat_agent_package_session_id", "") or "").strip()


def _create_agent_session_id(record: Any) -> str:
    return str(getattr(record, "create_agent_session_id", "") or "").strip()


def _evolve_agent_package_id(record: Any) -> str:
    return str(getattr(record, "evolve_agent_package_id", "") or "").strip()


def _record_order_key(record: Any) -> tuple[str, str]:
    return (
        str(getattr(record, "updated_at", "") or ""),
        str(getattr(record, "session_id", "") or ""),
    )


def _turn_request_ids(turns: object) -> list[str]:
    if not isinstance(turns, list):
        return []
    request_ids: list[str] = []
    for turn in turns:
        request_id = str(getattr(turn, "request_id", "") or "").strip()
        if request_id:
            request_ids.append(request_id)
    return request_ids


class _InterruptResumeTarget:
    def __init__(self, payload: dict[str, object]) -> None:
        self.mode = _normalized_optional(payload.get("mode") or payload.get("original_mode"))
        self.package_id = _normalized_optional(payload.get("package_id"))
        self.session_id = _normalized_optional(
            payload.get("agent_session_id") or payload.get("session_id") or payload.get("original_session_id")
        )
        self.request_id = _normalized_optional(
            payload.get("pending_request_id") or payload.get("original_request_id")
        )
        self.interrupt_id = _normalized_optional(payload.get("interrupt_id"))
        self.interrupt_event_id = _normalized_optional(payload.get("interrupt_event_id"))

    @property
    def explicit(self) -> bool:
        return any([
            self.mode,
            self.package_id,
            self.session_id,
            self.request_id,
            self.interrupt_id,
            self.interrupt_event_id,
        ])


def _interrupt_resume_target(payload: object) -> _InterruptResumeTarget:
    return _InterruptResumeTarget(payload if isinstance(payload, dict) else {})


def _pending_create_agent_matches(pending: object, target: _InterruptResumeTarget) -> bool:
    if target.mode and target.mode != "create_agent":
        return False
    return _pending_common_matches(
        session_id=getattr(pending, "session_id", None),
        request_id=getattr(pending, "request_id", None),
        interrupt_id=getattr(pending, "interrupt_id", None),
        interrupt_event_id=getattr(pending, "interrupt_event_id", None),
        target=target,
    )


def _pending_evolution_matches(pending: object, target: _InterruptResumeTarget) -> bool:
    if target.mode and target.mode != "evolve_agent":
        return False
    if target.package_id and target.package_id != _normalized_optional(getattr(pending, "package_id", None)):
        return False
    return _pending_common_matches(
        session_id=getattr(pending, "session_id", None),
        request_id=getattr(pending, "request_id", None),
        interrupt_id=getattr(pending, "interrupt_id", None),
        interrupt_event_id=getattr(pending, "interrupt_event_id", None),
        target=target,
    )


def _pending_agent_package_matches(pending: object, target: _InterruptResumeTarget) -> bool:
    if target.mode and target.mode not in {"agent_package", "chat"}:
        return False
    if target.package_id and target.package_id != _normalized_optional(getattr(pending, "package_id", None)):
        return False
    normalizer = getattr(pending, "normalizer", None)
    return _pending_common_matches(
        session_id=getattr(pending, "session_id", None),
        request_id=getattr(normalizer, "request_id", None),
        interrupt_id=getattr(pending, "interrupt_id", None),
        interrupt_event_id=getattr(pending, "interrupt_event_id", None),
        target=target,
    )


def _pending_common_matches(
    *,
    session_id: object,
    request_id: object,
    interrupt_id: object,
    interrupt_event_id: object,
    target: _InterruptResumeTarget,
) -> bool:
    if target.interrupt_event_id:
        return target.interrupt_event_id == _normalized_optional(interrupt_event_id)
    if target.session_id and target.session_id != _normalized_optional(session_id):
        return False
    if target.request_id and target.request_id != _normalized_optional(request_id):
        return False
    if target.interrupt_id and target.interrupt_id != _normalized_optional(interrupt_id):
        return False
    return True


def _publish_confirmation_ready(workspace: CreateAgentWorkspace) -> bool:
    active = workspace.read_system_state().active_stage()
    if active is None or active.system_id != "validation_publish":
        return False
    validation = workspace.read_validation()
    if validation is None or validation.status != "passed":
        return False
    validation_state = workspace.read_validation_state()
    if validation_state is None or validation_state.validation_scope != "full_static":
        return False
    if validation.validation_scope != "full_static":
        return False
    return validation_state.package_fingerprint == package_fingerprint(workspace.root)


def _normalized_optional(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _session_mode(mode: str | None) -> str | None:
    return mode if mode in SESSION_MODES else None


def _command_evolution_package_id(command: FactoryFrontendCommand, mode: str | None) -> str | None:
    if mode != "evolve_agent" or not isinstance(command.payload, dict):
        return None
    value = str(command.payload.get("package_id") or "").strip()
    return value or None
