from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class AgentSessionTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    created_at: str
    user_input: str | None = None
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
