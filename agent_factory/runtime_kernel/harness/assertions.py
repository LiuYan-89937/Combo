from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class AssertPathContains:
    def __init__(self, expected_node_ids: Iterable[str]) -> None:
        self.expected_node_ids = list(expected_node_ids)

    def check(self, *, event_log: list[dict[str, Any]]) -> dict[str, Any]:
        seen = [item.get("node_id") for item in event_log if item.get("event_type") == "node_entered"]
        ok = all(node_id in seen for node_id in self.expected_node_ids)
        return {"type": "path_contains", "ok": ok, "expected": self.expected_node_ids, "seen": seen}


class AssertToolCalled:
    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id

    def check(self, *, final_state: Any) -> dict[str, Any]:
        results = getattr(getattr(final_state, "tools", None), "tool_results", []) or []
        ok = any(item.get("output", {}).get("tool_id") == self.tool_id or item.get("tool_id") == self.tool_id for item in results)
        return {"type": "tool_called", "ok": ok, "tool_id": self.tool_id}


class AssertPolicyBlocked:
    def check(self, *, final_state: Any) -> dict[str, Any]:
        blocked = bool(getattr(getattr(final_state, "policy", None), "blocked", False))
        return {"type": "policy_blocked", "ok": blocked}


class AssertContextBuilt:
    def __init__(self, context_key: str) -> None:
        self.context_key = context_key

    def check(self, *, final_state: Any) -> dict[str, Any]:
        model_context = getattr(getattr(final_state, "context", None), "model_context", {}) or {}
        tool_context = getattr(getattr(final_state, "context", None), "tool_context", {}) or {}
        ok = self.context_key in model_context or self.context_key in tool_context
        return {"type": "context_built", "ok": ok, "context_key": self.context_key}


class AssertCheckpointCreated:
    def check(self, *, final_state: Any) -> dict[str, Any]:
        refs = getattr(getattr(final_state, "observability", None), "debug_refs", []) or []
        ok = any(item.get("kind") == "checkpoint" for item in refs)
        return {"type": "checkpoint_created", "ok": ok}


class AssertResumeEvent:
    def check(self, *, event_log: list[dict[str, Any]]) -> dict[str, Any]:
        ok = any(item.get("event_type") == "resume_completed" for item in event_log)
        return {"type": "resume_event", "ok": ok}


class AssertFinalAnswer:
    def __init__(self, expected: str) -> None:
        self.expected = expected

    def check(self, *, final_state: Any) -> dict[str, Any]:
        answer = getattr(getattr(final_state, "conversation", None), "final_answer", None)
        return {"type": "final_answer", "ok": answer == self.expected, "expected": self.expected, "actual": answer}
