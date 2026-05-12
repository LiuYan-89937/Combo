from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid
from typing import Literal

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.runtime_kernel.state.messages import MessageRecord, dump_messages, load_messages


FactorySessionMode = Literal["chat", "create_agent"]

DEFAULT_SESSION_ROOT = ".agentfactory/sessions"
DEFAULT_CHECKPOINT_PATH = ".agentfactory/checkpoints/factory.sqlite"

_CHECKPOINTER_CONTEXTS: list[object] = []
_PERSISTENT_CHECKPOINTER_IDS: set[int] = set()


class FactorySessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    created_at: str
    updated_at: str
    first_user_input: str | None = None
    display_title: str | None = None
    current_mode: FactorySessionMode | None = None
    chat_thread_id: str
    create_agent_thread_id: str
    chat_turn_count: int = 0
    create_agent_turn_count: int = 0
    chat_messages: list[MessageRecord] = Field(default_factory=list)
    create_agent_messages: list[MessageRecord] = Field(default_factory=list)


@dataclass(slots=True)
class FactorySessionConfig:
    root: Path

    @classmethod
    def from_env(cls) -> "FactorySessionConfig":
        root = Path(os.getenv("AGENTFACTORY_SESSION_ROOT", DEFAULT_SESSION_ROOT)).expanduser()
        return cls(root=root)


class FactorySessionManager:
    def __init__(self, config: FactorySessionConfig | None = None) -> None:
        self.config = config or FactorySessionConfig.from_env()
        self.config.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "FactorySessionManager":
        return cls(FactorySessionConfig.from_env())

    def create(self) -> FactorySessionRecord:
        now = _now()
        record = FactorySessionRecord(
            session_id=uuid.uuid4().hex,
            created_at=now,
            updated_at=now,
            chat_thread_id=f"factory-chat-{uuid.uuid4().hex}",
            create_agent_thread_id=f"factory-create-{uuid.uuid4().hex}",
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

    def latest(self) -> FactorySessionRecord | None:
        records = self.list_sessions()
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

    def remember_first_user_input(self, session_id: str, value: str) -> FactorySessionRecord:
        record = self.load(session_id)
        if not record.first_user_input:
            record.first_user_input = value.strip() or None
        if not record.display_title:
            record.display_title = _display_title(record.first_user_input)
        self.save(record)
        return record

    def thread_id(self, record: FactorySessionRecord, mode: FactorySessionMode) -> str:
        if mode == "chat":
            return record.chat_thread_id
        return record.create_agent_thread_id

    def messages(self, record: FactorySessionRecord, mode: FactorySessionMode) -> list[BaseMessage]:
        if mode == "chat":
            return load_messages(record.chat_messages)
        return load_messages(record.create_agent_messages)

    def replace_messages(
        self,
        session_id: str,
        mode: FactorySessionMode,
        messages: list[BaseMessage],
    ) -> FactorySessionRecord:
        record = self.load(session_id)
        if not record.first_user_input:
            record.first_user_input = _first_user_input(messages)
        if not record.display_title:
            record.display_title = _display_title(record.first_user_input)
        if mode == "chat":
            record.chat_messages = dump_messages(messages)
            record.chat_turn_count = _human_message_count(messages)
        else:
            record.create_agent_messages = dump_messages(messages)
            record.create_agent_turn_count = _human_message_count(messages)
        self.save(record)
        return record

    def _path(self, session_id: str) -> Path:
        return self.config.root / f"{session_id}.json"


def checkpoint_path_from_env() -> Path:
    return Path(os.getenv("AGENTFACTORY_CHECKPOINT_PATH", DEFAULT_CHECKPOINT_PATH)).expanduser()


def build_factory_checkpointer():
    checkpoint_path = checkpoint_path_from_env()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ModuleNotFoundError:
        from langgraph.checkpoint.memory import InMemorySaver

        return InMemorySaver()
    checkpointer = SqliteSaver.from_conn_string(str(checkpoint_path))
    if hasattr(checkpointer, "__enter__"):
        _CHECKPOINTER_CONTEXTS.append(checkpointer)
        saver = checkpointer.__enter__()
        _PERSISTENT_CHECKPOINTER_IDS.add(id(saver))
        return saver
    _PERSISTENT_CHECKPOINTER_IDS.add(id(checkpointer))
    return checkpointer


def is_factory_checkpointer_persistent(checkpointer: object | None) -> bool:
    return id(checkpointer) in _PERSISTENT_CHECKPOINTER_IDS


def _human_message_count(messages: list[BaseMessage]) -> int:
    return sum(1 for message in messages if message.__class__.__name__ == "HumanMessage")


def _first_user_input(messages: list[BaseMessage]) -> str | None:
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
