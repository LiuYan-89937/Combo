from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.runtime_attachments import normalized_runtime_attachments
from agent_factory.trace_system import JSONLTraceStore


class AgentSessionTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    created_at: str
    user_input: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    reasoning_content: str | None = None
    final_answer: str | None = None
    status: str | None = None
    trace_ref: dict[str, str] | None = None


class AgentSessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    agent_id: str
    thread_id: str
    created_at: str
    updated_at: str
    first_user_input: str | None = None
    display_title: str | None = None
    turn_count: int = 0
    turns: list[AgentSessionTurn] = Field(default_factory=list)
    runtime_refs: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentSessionConfig:
    root: Path = Path(".agent_runtime/sessions")


@dataclass(frozen=True, slots=True)
class AgentSessionDeletionResult:
    record: AgentSessionRecord
    deleted_trace_count: int


class AgentSessionManager:
    def __init__(self, config: AgentSessionConfig | None = None) -> None:
        self.config = config or AgentSessionConfig()
        self.config.root.mkdir(parents=True, exist_ok=True)

    def create(self, *, agent_id: str, first_user_input: str | None = None) -> AgentSessionRecord:
        now = _now()
        record = AgentSessionRecord(
            session_id=uuid4().hex,
            agent_id=agent_id,
            thread_id=f"agent-{agent_id}-{uuid4().hex}",
            created_at=now,
            updated_at=now,
            first_user_input=(first_user_input or "").strip() or None,
            display_title=_display_title(first_user_input),
            runtime_refs=_runtime_refs(self.config.root),
        )
        self.save(record)
        return record

    def load(self, session_id: str) -> AgentSessionRecord:
        path = self._path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Agent session not found: {session_id}")
        return AgentSessionRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def exists(self, session_id: str) -> bool:
        return self._path(session_id).exists()

    def load_optional(self, session_id: str) -> AgentSessionRecord | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        return AgentSessionRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, record: AgentSessionRecord) -> None:
        record.updated_at = _now()
        self._path(record.session_id).write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_sessions(self, *, agent_id: str | None = None) -> list[AgentSessionRecord]:
        records: list[AgentSessionRecord] = []
        for path in self.config.root.glob("*.json"):
            try:
                record = AgentSessionRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if agent_id is not None and record.agent_id != agent_id:
                continue
            records.append(record)
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def delete(self, session_id: str) -> AgentSessionDeletionResult:
        record = self.load(session_id)
        deleted_trace_count = _delete_record_traces(record)
        self._path(record.session_id).unlink(missing_ok=True)
        return AgentSessionDeletionResult(record=record, deleted_trace_count=deleted_trace_count)

    def delete_if_exists(self, session_id: str) -> AgentSessionDeletionResult | None:
        record = self.load_optional(session_id)
        if record is None:
            return None
        deleted_trace_count = _delete_record_traces(record)
        self._path(record.session_id).unlink(missing_ok=True)
        return AgentSessionDeletionResult(record=record, deleted_trace_count=deleted_trace_count)

    def touch_turn(
        self,
        session_id: str,
        *,
        first_user_input: str | None = None,
        user_input: str | None = None,
        reasoning_content: str | None = None,
        final_answer: str | None = None,
        status: str | None = None,
        trace_ref: dict[str, str] | None = None,
        attachments: Any = None,
    ) -> AgentSessionRecord:
        record = self.load(session_id)
        if not record.first_user_input:
            record.first_user_input = (first_user_input or "").strip() or None
        if not record.display_title:
            record.display_title = _display_title(record.first_user_input)
        if not record.runtime_refs:
            record.runtime_refs = _runtime_refs(self.config.root)
        record.turn_count += 1
        turn_input = (user_input or first_user_input or "").strip() or None
        record.turns.append(
            AgentSessionTurn(
                index=record.turn_count,
                created_at=_now(),
                user_input=turn_input,
                attachments=normalized_runtime_attachments(attachments),
                reasoning_content=(reasoning_content or "").strip() or None,
                final_answer=(final_answer or "").strip() or None,
                status=(status or "").strip() or None,
                trace_ref=trace_ref or None,
            )
        )
        self.save(record)
        return record

    def _path(self, session_id: str) -> Path:
        return self.config.root / f"{session_id}.json"


def _display_title(value: str | None, *, limit: int = 42) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 1]}…"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _runtime_refs(session_root: Path) -> dict[str, str]:
    root = session_root.expanduser().resolve()
    runtime_root = root.parent if root.name == "sessions" else root
    return {
        "runtime_root": str(runtime_root),
        "sessions": str(root),
        "checkpoints": str(runtime_root / "checkpoints"),
        "tool_outputs": str(runtime_root / "tool_outputs" / "records"),
        "state": str(runtime_root / "state"),
        "memory": str(runtime_root / "memory"),
        "trace": str(runtime_root / "trace"),
    }


def _delete_record_traces(record: AgentSessionRecord) -> int:
    default_trace_root = _trace_root(record.runtime_refs)
    deleted = 0
    seen: set[tuple[str, str]] = set()
    for turn in record.turns:
        ref = turn.trace_ref
        if not isinstance(ref, dict):
            continue
        trace_id = str(ref.get("trace_id") or "").strip()
        if not _is_safe_path_id(trace_id):
            continue
        trace_root = _trace_root(ref) or default_trace_root
        if trace_root is None:
            continue
        key = (str(trace_root), trace_id)
        if key in seen:
            continue
        seen.add(key)
        trace_dir = trace_root / "runs" / trace_id
        if trace_dir.exists():
            JSONLTraceStore(trace_root).delete_trace(trace_id)
            deleted += 1
    return deleted


def _trace_root(payload: dict[str, Any] | None) -> Path | None:
    if not isinstance(payload, dict):
        return None
    root = str(payload.get("trace_root") or payload.get("trace") or "").strip()
    if root:
        return Path(root).expanduser().resolve()
    trace_path = str(payload.get("trace_path") or "").strip()
    if not trace_path:
        return None
    path = Path(trace_path).expanduser().resolve()
    if path.parent.name != "runs":
        return None
    return path.parent.parent


def _is_safe_path_id(value: str) -> bool:
    return bool(value) and value not in {".", ".."} and "/" not in value and "\\" not in value
