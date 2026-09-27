from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from threading import RLock

from combo.file_atomic import atomic_write_text


class AgentInstructionStore:
    """User-managed Agent.md, separate from searchable conversation memory."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path).expanduser().resolve()
        self._lock = RLock()

    def read(self) -> dict[str, str]:
        with self._lock:
            content = self._path.read_text(encoding="utf-8") if self._path.is_file() else ""
            return {"content": content, "digest": sha256(content.encode("utf-8")).hexdigest()}

    def replace(self, *, content: str, expected_digest: str) -> dict[str, str]:
        with self._lock:
            current = self.read()
            if current["digest"] != expected_digest:
                raise RuntimeError("agent_instructions_changed")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self._path, content)
            return self.read()
