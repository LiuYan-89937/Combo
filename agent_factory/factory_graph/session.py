from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.paths import resolve_project_path
from agent_factory.runtime_kernel.persistence import (
    LangGraphCheckpointerConfig,
    LangGraphCheckpointerFactory,
    LangGraphCheckpointerHandle,
    is_checkpointer_persistent,
)


FactorySessionMode = Literal["chat", "create_agent", "evolve_agent"]
FactoryCheckpointerBackend = Literal["sqlite", "memory"]

DEFAULT_SESSION_ROOT = ".agentfactory/sessions"
DEFAULT_CHECKPOINT_PATH = ".agentfactory/checkpoints/factory.sqlite"
DEFAULT_CHECKPOINTER_BACKEND: FactoryCheckpointerBackend = "sqlite"


class FactorySessionTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    created_at: str
    updated_at: str
    request_id: str | None = None
    user_input: str | None = None
    final_answer: str | None = None
    status: str | None = None


class FactorySessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    created_at: str
    updated_at: str
    first_user_input: str | None = None
    display_title: str | None = None
    current_mode: FactorySessionMode | None = None
    chat_agent_package_session_id: str | None = None
    create_agent_session_id: str | None = None
    evolve_agent_package_id: str | None = None
    chat_turn_count: int = 0
    create_agent_turn_count: int = 0
    evolve_agent_turn_count: int = 0
    chat_turns: list[FactorySessionTurn] = Field(default_factory=list)
    create_agent_turns: list[FactorySessionTurn] = Field(default_factory=list)
    evolve_agent_turns: list[FactorySessionTurn] = Field(default_factory=list)


@dataclass(slots=True)
class FactorySessionConfig:
    root: Path

    @classmethod
    def from_env(cls) -> "FactorySessionConfig":
        root = resolve_project_path(os.getenv("AGENTFACTORY_SESSION_ROOT", DEFAULT_SESSION_ROOT))
        return cls(root=root)


@dataclass(frozen=True, slots=True)
class FactoryCheckpointerConfig:
    backend: FactoryCheckpointerBackend
    path: Path

    @classmethod
    def from_env(cls) -> "FactoryCheckpointerConfig":
        raw_backend = os.getenv("AGENTFACTORY_CHECKPOINTER_BACKEND", DEFAULT_CHECKPOINTER_BACKEND).strip().lower()
        if raw_backend not in {"sqlite", "memory"}:
            raise ValueError(
                "AGENTFACTORY_CHECKPOINTER_BACKEND must be one of: sqlite, memory"
            )
        return cls(
            backend=raw_backend,
            path=checkpoint_path_from_env(),
        )


@dataclass(frozen=True, slots=True)
class FactoryCheckpointerHandle:
    saver: Any
    backend: FactoryCheckpointerBackend
    persistent: bool
    path: Path | None = None


class FactorySessionManager:
    def __init__(self, config: FactorySessionConfig | None = None) -> None:
        self.config = config or FactorySessionConfig.from_env()
        self.config.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "FactorySessionManager":
        return cls(FactorySessionConfig.from_env())

    def create(self, *, mode: FactorySessionMode | None = None) -> FactorySessionRecord:
        now = _now()
        record = FactorySessionRecord(
            session_id=uuid.uuid4().hex,
            created_at=now,
            updated_at=now,
            current_mode=mode,
        )
        self.save(record)
        return record

    def load(self, session_id: str) -> FactorySessionRecord:
        path = self._path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Factory session not found: {session_id}")
        return FactorySessionRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, record: FactorySessionRecord) -> None:
        record.updated_at = _now()
        self._path(record.session_id).write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def latest(self, *, mode: FactorySessionMode | None = None) -> FactorySessionRecord | None:
        records = self.list_sessions()
        if mode is not None:
            records = [record for record in records if _record_matches_mode(record, mode)]
        if not records:
            return None
        return records[0]

    def list_sessions(self) -> list[FactorySessionRecord]:
        records: list[FactorySessionRecord] = []
        for path in self.config.root.glob("*.json"):
            try:
                records.append(FactorySessionRecord.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def set_mode(self, session_id: str, mode: FactorySessionMode | None) -> FactorySessionRecord:
        record = self.load(session_id)
        record.current_mode = mode
        self.save(record)
        return record

    def set_evolution_package(self, session_id: str, package_id: str) -> FactorySessionRecord:
        record = self.load(session_id)
        record.current_mode = "evolve_agent"
        record.evolve_agent_package_id = package_id.strip() or None
        self.save(record)
        return record

    def remember_first_user_input(self, session_id: str, value: str) -> FactorySessionRecord:
        record = self.load(session_id)
        if not record.first_user_input:
            record.first_user_input = value.strip() or None
        if not record.display_title:
            record.display_title = _display_title(record.first_user_input)
        self.save(record)
        return record

    def thread_id(self, record: FactorySessionRecord, mode: FactorySessionMode) -> str:
        raise ValueError(f"{mode} mode is backed by a SystemPackage session")

    def messages(self, record: FactorySessionRecord, mode: FactorySessionMode) -> list[Any]:
        raise ValueError(f"{mode} mode messages are stored in the SystemPackage session")

    def replace_messages(
        self,
        session_id: str,
        mode: FactorySessionMode,
        messages: list[Any],
    ) -> FactorySessionRecord:
        record = self.load(session_id)
        if not record.first_user_input:
            record.first_user_input = _first_user_input(messages)
        if not record.display_title:
            record.display_title = _display_title(record.first_user_input)
        if mode == "chat":
            record.chat_turn_count = _human_message_count(messages)
        elif mode == "create_agent":
            record.create_agent_turn_count = _human_message_count(messages)
        elif mode == "evolve_agent":
            record.evolve_agent_turn_count = _human_message_count(messages)
        self.save(record)
        return record

    def start_turn(
        self,
        session_id: str,
        mode: FactorySessionMode,
        *,
        request_id: str | None,
        user_input: str,
    ) -> FactorySessionRecord:
        record = self.load(session_id)
        _remember_record_title(record, user_input)
        record.current_mode = mode
        turns = _turns_for_mode(record, mode)
        turn = _find_turn(turns, request_id=request_id)
        now = _now()
        if turn is None:
            turns.append(
                FactorySessionTurn(
                    index=len(turns) + 1,
                    created_at=now,
                    updated_at=now,
                    request_id=(request_id or "").strip() or None,
                    user_input=user_input.strip() or None,
                    status="running",
                )
            )
        else:
            if not turn.user_input:
                turn.user_input = user_input.strip() or None
            turn.status = turn.status or "running"
            turn.updated_at = now
        _sync_turn_count(record, mode)
        self.save(record)
        return record

    def finish_turn(
        self,
        session_id: str,
        mode: FactorySessionMode,
        *,
        request_id: str | None,
        final_answer: str | None,
        status: str,
    ) -> FactorySessionRecord:
        record = self.load(session_id)
        turns = _turns_for_mode(record, mode)
        turn = _find_turn(turns, request_id=request_id)
        if turn is None and turns:
            turn = turns[-1]
        if turn is not None:
            turn.final_answer = (final_answer or "").strip() or None
            turn.status = status.strip() or None
            turn.updated_at = _now()
        _sync_turn_count(record, mode)
        self.save(record)
        return record

    def replace_turns_from_agent_session(
        self,
        session_id: str,
        mode: FactorySessionMode,
        agent_turns: list[dict[str, Any]],
    ) -> FactorySessionRecord:
        record = self.load(session_id)
        turns: list[FactorySessionTurn] = []
        for index, raw_turn in enumerate(agent_turns, start=1):
            if not isinstance(raw_turn, dict):
                continue
            user_input = str(raw_turn.get("user_input") or "").strip() or None
            final_answer = str(raw_turn.get("final_answer") or "").strip() or None
            if not user_input and not final_answer:
                continue
            created_at = str(raw_turn.get("created_at") or _now())
            turns.append(
                FactorySessionTurn(
                    index=_safe_turn_index(raw_turn.get("index"), fallback=index),
                    created_at=created_at,
                    updated_at=created_at,
                    user_input=user_input,
                    final_answer=final_answer,
                    status=str(raw_turn.get("status") or "").strip() or None,
                )
            )
        _set_turns_for_mode(record, mode, turns)
        first_input = _first_turn_input(turns)
        if first_input:
            _remember_record_title(record, first_input)
        record.current_mode = mode
        _sync_turn_count(record, mode)
        self.save(record)
        return record

    def _path(self, session_id: str) -> Path:
        return self.config.root / f"{session_id}.json"


def checkpoint_path_from_env() -> Path:
    return resolve_project_path(os.getenv("AGENTFACTORY_CHECKPOINT_PATH", DEFAULT_CHECKPOINT_PATH))


class FactoryCheckpointerFactory:
    def build(self, config: FactoryCheckpointerConfig | None = None) -> FactoryCheckpointerHandle:
        config = config or FactoryCheckpointerConfig.from_env()
        handle = LangGraphCheckpointerFactory().build(
            LangGraphCheckpointerConfig(backend=config.backend, path=config.path)
        )
        return FactoryCheckpointerHandle(
            saver=handle.saver,
            backend=handle.backend,
            persistent=handle.persistent,
            path=handle.path,
        )


def build_factory_checkpointer():
    return build_factory_checkpointer_handle().saver


def build_factory_checkpointer_handle() -> FactoryCheckpointerHandle:
    return FactoryCheckpointerFactory().build()


def is_factory_checkpointer_persistent(checkpointer: object | None) -> bool:
    return is_checkpointer_persistent(checkpointer)


def _human_message_count(messages: list[Any]) -> int:
    return sum(1 for message in messages if message.__class__.__name__ == "HumanMessage")


def _first_user_input(messages: list[Any]) -> str | None:
    for message in messages:
        if message.__class__.__name__ == "HumanMessage":
            content = message.content
            if isinstance(content, str):
                value = content.strip()
                if value:
                    return value
    return None


def _display_title(value: str | None, *, limit: int = 42) -> str | None:
    if not value:
        return None
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 1]}…"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_matches_mode(record: FactorySessionRecord, mode: FactorySessionMode) -> bool:
    if mode == "chat":
        return (
            record.current_mode == mode
            or record.chat_turn_count > 0
            or bool(record.chat_turns)
            or bool(record.chat_agent_package_session_id)
        )
    if mode == "create_agent":
        return (
            record.current_mode == mode
            or record.create_agent_turn_count > 0
            or bool(record.create_agent_turns)
            or bool(record.create_agent_session_id)
        )
    return (
        record.current_mode == mode
        or record.evolve_agent_turn_count > 0
        or bool(record.evolve_agent_turns)
        or bool(record.evolve_agent_package_id)
    )


def _turns_for_mode(record: FactorySessionRecord, mode: FactorySessionMode) -> list[FactorySessionTurn]:
    if mode == "chat":
        return record.chat_turns
    if mode == "create_agent":
        return record.create_agent_turns
    if mode == "evolve_agent":
        return record.evolve_agent_turns
    raise ValueError(f"{mode} mode does not have Factory session turns")


def _set_turns_for_mode(record: FactorySessionRecord, mode: FactorySessionMode, turns: list[FactorySessionTurn]) -> None:
    if mode == "chat":
        record.chat_turns = turns
        return
    if mode == "create_agent":
        record.create_agent_turns = turns
        return
    if mode == "evolve_agent":
        record.evolve_agent_turns = turns
        return
    raise ValueError(f"{mode} mode does not have Factory session turns")


def _find_turn(turns: list[FactorySessionTurn], *, request_id: str | None) -> FactorySessionTurn | None:
    needle = (request_id or "").strip()
    if not needle:
        return None
    for turn in reversed(turns):
        if turn.request_id == needle:
            return turn
    return None


def _sync_turn_count(record: FactorySessionRecord, mode: FactorySessionMode) -> None:
    if mode == "chat":
        record.chat_turn_count = len(record.chat_turns)
    elif mode == "create_agent":
        record.create_agent_turn_count = len(record.create_agent_turns)
    elif mode == "evolve_agent":
        record.evolve_agent_turn_count = len(record.evolve_agent_turns)


def _safe_turn_index(value: Any, *, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _remember_record_title(record: FactorySessionRecord, user_input: str | None) -> None:
    if not record.first_user_input:
        record.first_user_input = (user_input or "").strip() or None
    if not record.display_title:
        record.display_title = _display_title(record.first_user_input)


def _first_turn_input(turns: list[FactorySessionTurn]) -> str | None:
    for turn in turns:
        value = (turn.user_input or "").strip()
        if value:
            return value
    return None
