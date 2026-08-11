from __future__ import annotations

from dataclasses import asdict
from typing import Any

from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import PendingAgentPackageRun


class RuntimeSessionCommandMixin:
    def resume_interrupt(self, command: FactoryFrontendCommand) -> None:
        target = _interrupt_resume_target(command.payload)
        group_run_id = str(command.payload.get("group_run_id") or "").strip()
        if group_run_id:
            pending = self.pending_agent_group_runs.pop(group_run_id, None)
            if pending is None:
                self._emit_error(command, "no matching agent-group interrupt to resume")
                return
            self.resume_agent_group_interrupt(command, pending)
            return
        pending = self._take_pending_agent_package_run(target)
        if pending is not None:
            self._resume_agent_package_interrupt(command, pending)
            return
        self._emit_error(
            command,
            "no matching pending interrupt to resume" if target.explicit else "no pending interrupt to resume",
        )

    def _remember_pending_agent_package_run(self, pending: PendingAgentPackageRun) -> None:
        key = _pending_agent_package_key(pending)
        with self.pending_agent_package_runs_lock:
            self.pending_agent_package_runs[key] = pending

    def _has_pending_agent_package_run(self, package_id: str, session_id: str) -> bool:
        key = (str(package_id).strip(), str(session_id).strip())
        with self.pending_agent_package_runs_lock:
            return key in self.pending_agent_package_runs

    def _take_pending_agent_package_for_message(
        self,
        package_id: str,
        session_id: str,
    ) -> PendingAgentPackageRun | None:
        key = (str(package_id).strip(), str(session_id).strip())
        with self.pending_agent_package_runs_lock:
            return self.pending_agent_package_runs.pop(key, None)

    def _take_pending_agent_package_run(
        self,
        target: _InterruptResumeTarget,
    ) -> PendingAgentPackageRun | None:
        with self.pending_agent_package_runs_lock:
            matches = [
                (key, pending)
                for key, pending in self.pending_agent_package_runs.items()
                if _pending_agent_package_matches(pending, target)
            ]
            if len(matches) != 1:
                return None
            key, pending = matches[0]
            self.pending_agent_package_runs.pop(key, None)
            return pending

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

    def _session_id(self) -> str | None:
        return str(getattr(self.session_record, "session_id", "") or "").strip() or None

    def checkpointer_payload(self) -> dict[str, object]:
        return {"backend": "system_package", "persistent": True, "path": None}

    def _options_payload(self) -> dict[str, object]:
        return asdict(self.options)


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
        return any(
            [
                self.mode,
                self.package_id,
                self.session_id,
                self.request_id,
                self.interrupt_id,
                self.interrupt_event_id,
            ]
        )


def _interrupt_resume_target(payload: object) -> _InterruptResumeTarget:
    return _InterruptResumeTarget(payload if isinstance(payload, dict) else {})


def _pending_agent_package_matches(pending: object, target: _InterruptResumeTarget) -> bool:
    if target.mode and target.mode not in {"agent_package", "agent_group"}:
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


def _pending_agent_package_key(pending: object) -> tuple[str, str]:
    package_id = _normalized_optional(getattr(pending, "package_id", None))
    session_id = _normalized_optional(getattr(pending, "session_id", None))
    if not package_id or not session_id:
        raise ValueError("pending agent package run requires package_id and session_id")
    return package_id, session_id


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


def _normalized_optional(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
