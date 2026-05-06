from __future__ import annotations

from collections import defaultdict
from typing import Any

from agent_factory.runtime_kernel.state import RuntimeState


class InMemoryMemoryEngine:
    def __init__(self) -> None:
        self._store: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def recall(self, *, state: RuntimeState, binding: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        session_items = list(self._store.get(state.run.session_id, []))
        state.memory.short_term_snapshot = {"count": len(session_items)}
        return session_items[-5:]

    def write(self, *, state: RuntimeState, binding: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        item = {
            "input": state.conversation.current_user_input,
            "answer": state.conversation.final_answer,
            "turn_index": state.conversation.turn_index,
        }
        self._store[state.run.session_id].append(item)
        return [item]
