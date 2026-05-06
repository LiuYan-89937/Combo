from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime.redaction import redact_secrets
from agent_factory.package import PackageLoader


class AgentMemoryRecord(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    run_id: str
    session_id: str
    type: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentMemoryStore:
    def __init__(self, package_path: str | Path, *, loader: PackageLoader | None = None) -> None:
        self.package_path = Path(package_path)
        self.loader = loader or PackageLoader()
        package = self.loader.load_full_package(self.package_path)
        self.spec = package.memory
        self.path = self.package_path / self.spec.session_memory_file
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: AgentMemoryRecord) -> None:
        if not self.spec.enabled:
            return
        data = record.model_dump(mode="json")
        if self.spec.redact_before_storage:
            data = redact_secrets(data)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(data, ensure_ascii=False) + "\n")

    def list_recent(self, *, limit: int = 20, session_id: str | None = None) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if session_id and item.get("session_id") != session_id:
                continue
            rows.append(item)
        return rows[-limit:]

    def clear_session(self, *, session_id: str) -> int:
        if not self.path.exists():
            return 0
        kept: list[str] = []
        removed = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if item.get("session_id") == session_id:
                removed += 1
                continue
            kept.append(line)
        content = "\n".join(kept)
        if content:
            content += "\n"
        self.path.write_text(content, encoding="utf-8")
        return removed

    def recent_messages(
        self,
        *,
        session_id: str,
        limit_turns: int,
    ) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        for item in self.list_recent(limit=limit_turns, session_id=session_id):
            if item.get("type") != "agent_turn":
                continue
            payload = item.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if payload.get("status") != "completed":
                continue
            tool_results = payload.get("tool_results") or []
            if any(isinstance(result, dict) and result.get("status") == "interrupted" for result in tool_results):
                continue
            user_input = payload.get("user_input")
            answer = payload.get("answer")
            if isinstance(user_input, str) and user_input.strip():
                messages.append(HumanMessage(content=user_input))
            if isinstance(answer, str) and answer.strip():
                messages.append(AIMessage(content=answer))
        return messages
