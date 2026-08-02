from __future__ import annotations

from typing import Any


BACKGROUND_TASK_SOURCE_TO_KIND = {
    "agent_manufacture": "manufacture",
    "agent_evolve": "evolve",
    "agent_delegate": "delegate",
    "agent_team": "team",
}
BACKGROUND_TASK_KINDS = frozenset(BACKGROUND_TASK_SOURCE_TO_KIND.values())


def normalize_background_task_metadata(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("background_task must be an object")
    allowed = {"id", "kind", "source_tool"}
    unsupported = sorted(str(key) for key in value if key not in allowed)
    if unsupported:
        raise ValueError("unsupported background_task fields: " + ", ".join(unsupported))
    task_id = str(value.get("id") or "").strip()
    kind = str(value.get("kind") or "").strip()
    source_tool = str(value.get("source_tool") or "").strip()
    if not task_id:
        raise ValueError("background_task.id is required")
    expected_kind = BACKGROUND_TASK_SOURCE_TO_KIND.get(source_tool)
    if expected_kind is None:
        raise ValueError(f"unsupported background_task.source_tool: {source_tool}")
    if kind != expected_kind:
        raise ValueError(f"background_task kind {kind} does not match source tool {source_tool}")
    return {"id": task_id, "kind": kind, "source_tool": source_tool}
