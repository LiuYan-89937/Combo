from __future__ import annotations

from collections.abc import Callable
from threading import RLock


class RuntimeRequestCommitFence:
    """Prevents a stopped request from committing late runtime side effects."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._cancelled: dict[str, bool] = {}

    def begin(self, request_id: str) -> None:
        with self._lock:
            self._cancelled.setdefault(request_id, False)

    def cancel(self, request_id: str | None = None) -> int:
        target = (request_id or "").strip()
        with self._lock:
            if target:
                if target not in self._cancelled:
                    return 0
                self._cancelled[target] = True
                return 1
            for active_request_id in self._cancelled:
                self._cancelled[active_request_id] = True
            return len(self._cancelled)

    def is_cancelled(self, request_id: str | None) -> bool:
        if not request_id:
            return False
        with self._lock:
            return self._cancelled.get(request_id, False)

    def commit(self, request_id: str | None, callback: Callable[[], None]) -> bool:
        with self._lock:
            if request_id and self._cancelled.get(request_id, False):
                return False
            callback()
            return True

    def finish(self, request_id: str) -> None:
        with self._lock:
            self._cancelled.pop(request_id, None)
