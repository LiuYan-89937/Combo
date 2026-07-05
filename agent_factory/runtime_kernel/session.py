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
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    request_id: str | None = None
    user_input: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    reasoning_content: str | None = None
    final_answer: str | None = None
    tool_activities: list[dict[str, Any]] = Field(default_factory=list)
    status: str | None = None
    trace_ref: dict[str, str] | None = None


class AgentSessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    agent_id: str
    thread_id: str
    session_kind: str = "normal"
    collaboration_id: str | None = None
    collaboration_task_id: str | None = None
    visible_in_agent_session_list: bool = True
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

    def create(
        self,
        *,
        agent_id: str,
        first_user_input: str | None = None,
        session_kind: str = "normal",
        collaboration_id: str | None = None,
        collaboration_task_id: str | None = None,
        visible_in_agent_session_list: bool | None = None,
    ) -> AgentSessionRecord:
        now = _now()
        kind = _normalize_session_kind(session_kind)
        record = AgentSessionRecord(
            session_id=uuid4().hex,
            agent_id=agent_id,
            thread_id=f"agent-{agent_id}-{uuid4().hex}",
            session_kind=kind,
            collaboration_id=_optional_text(collaboration_id),
            collaboration_task_id=_optional_text(collaboration_task_id),
            visible_in_agent_session_list=(
                kind == "normal" if visible_in_agent_session_list is None else bool(visible_in_agent_session_list)
            ),
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

    def list_sessions(
        self,
        *,
        agent_id: str | None = None,
        include_internal: bool = False,
    ) -> list[AgentSessionRecord]:
        records: list[AgentSessionRecord] = []
        for path in self.config.root.glob("*.json"):
            try:
                record = AgentSessionRecord.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if agent_id is not None and record.agent_id != agent_id:
                continue
            if not include_internal and not record.visible_in_agent_session_list:
                continue
            records.append(record)
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def update_metadata(
        self,
        session_id: str,
        *,
        session_kind: str | None = None,
        collaboration_id: str | None = None,
        collaboration_task_id: str | None = None,
        visible_in_agent_session_list: bool | None = None,
    ) -> AgentSessionRecord:
        record = self.load(session_id)
        if session_kind is not None:
            record.session_kind = _normalize_session_kind(session_kind)
        if collaboration_id is not None:
            record.collaboration_id = _optional_text(collaboration_id)
        if collaboration_task_id is not None:
            record.collaboration_task_id = _optional_text(collaboration_task_id)
        if visible_in_agent_session_list is not None:
            record.visible_in_agent_session_list = bool(visible_in_agent_session_list)
        self.save(record)
        return record

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
        request_id: str | None = None,
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
        turn_input = (user_input or first_user_input or "").strip() or None
        normalized_request_id = (request_id or "").strip() or None
        turn = _find_turn(record.turns, request_id=normalized_request_id) if normalized_request_id else None
        now = _now()
        if turn is None:
            turn = AgentSessionTurn(
                index=len(record.turns) + 1,
                created_at=now,
                updated_at=now,
                request_id=normalized_request_id,
                user_input=turn_input,
                attachments=normalized_runtime_attachments(attachments),
            )
            record.turns.append(turn)
        elif turn_input and not turn.user_input:
            turn.user_input = turn_input
        if not turn.attachments:
            turn.attachments = normalized_runtime_attachments(attachments)
        if reasoning_content is not None:
            turn.reasoning_content = (reasoning_content or "").strip() or None
        if final_answer is not None:
            turn.final_answer = (final_answer or "").strip() or None
        if status is not None:
            turn.status = (status or "").strip() or None
        if trace_ref is not None:
            turn.trace_ref = trace_ref or None
        turn.updated_at = now
        record.turn_count = len(record.turns)
        self.save(record)
        return record

    def finish_turn(
        self,
        session_id: str,
        *,
        request_id: str | None = None,
        reasoning_content: str | None = None,
        final_answer: str | None = None,
        status: str | None = None,
        trace_ref: dict[str, str] | None = None,
        tool_activities: list[dict[str, Any]] | None = None,
    ) -> AgentSessionRecord:
        record = self.load(session_id)
        normalized_request_id = (request_id or "").strip() or None
        turn = _find_turn(record.turns, request_id=normalized_request_id) if normalized_request_id else None
        if turn is None:
            turn = _latest_running_turn(record.turns) or (record.turns[-1] if record.turns else None)
        if turn is None:
            now = _now()
            turn = AgentSessionTurn(
                index=1,
                created_at=now,
                updated_at=now,
                request_id=normalized_request_id,
            )
            record.turns.append(turn)
        if reasoning_content is not None:
            turn.reasoning_content = (reasoning_content or "").strip() or None
        if final_answer is not None:
            turn.final_answer = (final_answer or "").strip() or None
        if status is not None:
            turn.status = (status or "").strip() or None
        if trace_ref is not None:
            turn.trace_ref = trace_ref or None
        if tool_activities is not None:
            turn.tool_activities = list(tool_activities)
        turn.updated_at = _now()
        record.turn_count = len(record.turns)
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


def _optional_text(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _normalize_session_kind(value: str | None) -> str:
    kind = str(value or "").strip() or "normal"
    allowed = {"normal", "collaboration_main", "collaboration_worker"}
    if kind not in allowed:
        raise ValueError(f"unsupported agent session kind: {kind}")
    return kind


def _find_turn(turns: list[AgentSessionTurn], *, request_id: str | None) -> AgentSessionTurn | None:
    if not request_id:
        return None
    for turn in turns:
        if turn.request_id == request_id:
            return turn
    return None


def _latest_running_turn(turns: list[AgentSessionTurn]) -> AgentSessionTurn | None:
    for turn in reversed(turns):
        if turn.status in {"running", "interrupted"}:
            return turn
    return None


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
