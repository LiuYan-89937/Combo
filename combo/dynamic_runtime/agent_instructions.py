from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sqlite3

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.runtime_protocol.contracts import utc_now_text


class AgentInstructionStore:
    """User-owned workspace system instructions; never searchable or model-writable memory."""

    def __init__(self, database: DynamicRuntimeDatabase, *, legacy_path: Path) -> None:
        self._database = database
        self._legacy_path = legacy_path

    def read(self, *, principal_id: str, workspace_id: str) -> dict[str, object]:
        with self._database.connection(query_only=True) as conn:
            _require_workspace(conn, principal_id, workspace_id, project_only=True)
            return _read(conn, workspace_id)

    def runtime_text(self, *, principal_id: str, workspace_id: str) -> str:
        with self._database.connection(query_only=True) as conn:
            workspace = _require_workspace(conn, principal_id, workspace_id, project_only=False)
            return str(_read(conn, workspace_id)["content"]) if workspace["mode"] == "project" else ""

    def replace(self, *, principal_id: str, workspace_id: str,
                content: str, expected_digest: str) -> dict[str, object]:
        with self._database.transaction() as conn:
            _require_workspace(conn, principal_id, workspace_id, project_only=True)
            current = _read(conn, workspace_id)
            if current["digest"] != expected_digest:
                raise RuntimeError("agent_instructions_changed")
            if content != current["content"]:
                conn.execute(
                    "insert into workspace_agent_instructions(workspace_id,content,revision,updated_at) "
                    "values (?,?,?,?) on conflict(workspace_id) do update set content=excluded.content, "
                    "revision=excluded.revision,updated_at=excluded.updated_at",
                    (workspace_id, content, int(current["revision"]) + 1, utc_now_text()),
                )
            return _read(conn, workspace_id)

    def legacy_draft(self) -> str:
        return self._legacy_path.read_text(encoding="utf-8") if self._legacy_path.is_file() else ""


def _read(conn: sqlite3.Connection, workspace_id: str) -> dict[str, object]:
    row = conn.execute("select content,revision from workspace_agent_instructions where workspace_id=?",
                       (workspace_id,)).fetchone()
    content = str(row["content"]) if row else ""
    return {"workspace_id": workspace_id, "content": content,
            "digest": sha256(content.encode("utf-8")).hexdigest(), "revision": int(row["revision"]) if row else 0}


def _require_workspace(conn: sqlite3.Connection, principal_id: str, workspace_id: str,
                       *, project_only: bool) -> sqlite3.Row:
    row = conn.execute("select mode from workspaces where workspace_id=? and principal_id=? and status='active'",
                       (workspace_id, principal_id)).fetchone()
    if row is None or (project_only and row["mode"] != "project"):
        raise LookupError("agent instructions require an owned shared workspace")
    return row
