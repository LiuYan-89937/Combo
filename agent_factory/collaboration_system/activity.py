from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Iterable


INSPECT_ACTIVITY_LIMIT_ENV = "AGENTFACTORY_COLLABORATION_INSPECT_ACTIVITY_LIMIT"
INSPECT_ACTIVITY_MAX_CHARS_ENV = "AGENTFACTORY_COLLABORATION_INSPECT_ACTIVITY_MAX_CHARS"
DEFAULT_INSPECT_ACTIVITY_LIMIT = 12
DEFAULT_INSPECT_ACTIVITY_MAX_CHARS = 4800
MIN_INSPECT_ACTIVITY_LIMIT = 1
MAX_INSPECT_ACTIVITY_LIMIT = 100
MIN_INSPECT_ACTIVITY_MAX_CHARS = 200
MAX_INSPECT_ACTIVITY_MAX_CHARS = 50000
VISIBLE_ACTIVITY_KINDS = frozenset(
    {
        "approval",
        "delivery",
        "plan",
        "progress",
        "reasoning_summary",
        "stage_output",
        "tool",
    }
)


@dataclass(frozen=True, slots=True)
class InspectActivityPolicy:
    limit: int = DEFAULT_INSPECT_ACTIVITY_LIMIT
    max_chars: int = DEFAULT_INSPECT_ACTIVITY_MAX_CHARS


def inspect_activity_policy(
    *,
    limit: Any = None,
    max_chars: Any = None,
) -> InspectActivityPolicy:
    configured_limit = _bounded_integer(
        os.getenv(INSPECT_ACTIVITY_LIMIT_ENV),
        default=DEFAULT_INSPECT_ACTIVITY_LIMIT,
        minimum=MIN_INSPECT_ACTIVITY_LIMIT,
        maximum=MAX_INSPECT_ACTIVITY_LIMIT,
    )
    configured_max_chars = _bounded_integer(
        os.getenv(INSPECT_ACTIVITY_MAX_CHARS_ENV),
        default=DEFAULT_INSPECT_ACTIVITY_MAX_CHARS,
        minimum=MIN_INSPECT_ACTIVITY_MAX_CHARS,
        maximum=MAX_INSPECT_ACTIVITY_MAX_CHARS,
    )
    return InspectActivityPolicy(
        limit=_bounded_integer(
            limit,
            default=configured_limit,
            minimum=MIN_INSPECT_ACTIVITY_LIMIT,
            maximum=MAX_INSPECT_ACTIVITY_LIMIT,
        ),
        max_chars=_bounded_integer(
            max_chars,
            default=configured_max_chars,
            minimum=MIN_INSPECT_ACTIVITY_MAX_CHARS,
            maximum=MAX_INSPECT_ACTIVITY_MAX_CHARS,
        ),
    )


def recent_task_activity(
    messages: Iterable[dict[str, Any]],
    *,
    task_ids: Iterable[str],
    policy: InspectActivityPolicy,
) -> dict[str, list[dict[str, Any]]]:
    ordered_task_ids = [str(task_id).strip() for task_id in task_ids if str(task_id).strip()]
    grouped: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in ordered_task_ids}
    for message in messages:
        task_id = str(message.get("task_id") or "").strip()
        kind = str(message.get("message_kind") or "").strip()
        content = str(message.get("content") or "").strip()
        if task_id not in grouped or kind not in VISIBLE_ACTIVITY_KINDS or not content:
            continue
        grouped[task_id].append(
            {
                "kind": kind,
                "content": content,
                "created_at": str(message.get("created_at") or ""),
                "event_ref": str(message.get("event_ref") or ""),
            }
        )

    pending = {task_id: list(reversed(items)) for task_id, items in grouped.items()}
    selected: dict[str, list[dict[str, Any]]] = {task_id: [] for task_id in ordered_task_ids}
    selected_count = 0
    selected_chars = 0
    while selected_count < policy.limit and selected_chars < policy.max_chars:
        advanced = False
        for task_id in ordered_task_ids:
            queue = pending[task_id]
            if not queue or selected_count >= policy.limit:
                continue
            remaining_chars = policy.max_chars - selected_chars
            if remaining_chars <= 0:
                break
            activity = queue.pop(0)
            content = str(activity["content"])
            if len(content) > remaining_chars:
                if selected_count > 0:
                    continue
                activity = {**activity, "content": _truncate(content, remaining_chars)}
                content = str(activity["content"])
            selected[task_id].append(activity)
            selected_count += 1
            selected_chars += len(content)
            advanced = True
        if not advanced:
            break

    return {
        task_id: list(reversed(items))
        for task_id, items in selected.items()
    }


def _bounded_integer(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    return value[: limit - 1] + "…"
