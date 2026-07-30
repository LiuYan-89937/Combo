from __future__ import annotations

import threading

from langgraph.runtime import RunControl


class RuntimeRunControlRegistry:
    """Own one LangGraph cooperative run control per active runtime request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._controls: dict[str, RunControl] = {}

    def register(self, request_id: str) -> RunControl:
        control = RunControl()
        with self._lock:
            self._controls[request_id] = control
        return control

    def request_drain(
        self,
        *,
        reason: str,
        request_id: str | None = None,
    ) -> int:
        target = (request_id or "").strip()
        with self._lock:
            controls = (
                [self._controls[target]]
                if target and target in self._controls
                else list(self._controls.values())
                if not target
                else []
            )
            for control in controls:
                control.request_drain(reason)
            return len(controls)

    def release(self, request_id: str, control: RunControl) -> None:
        with self._lock:
            if self._controls.get(request_id) is control:
                self._controls.pop(request_id, None)
