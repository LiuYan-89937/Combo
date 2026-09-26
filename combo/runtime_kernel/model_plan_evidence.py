from __future__ import annotations

import json
from typing import Any

PLAN_EVIDENCE_MAX_STEPS = 12
PLAN_RESULT_SUMMARY_MAX_CHARS = 900
PLAN_EVIDENCE_VALUE_MAX_CHARS = 240


def plan_evidence_text(state: Any) -> str:
    plan = getattr(state, "plan", None)
    if plan is None or getattr(plan, "status", "empty") == "empty":
        return ""
    current_step_id = getattr(plan, "current_step_id", None) or ""
    steps = list(getattr(plan, "steps", []) or [])
    lines = [
        "Current dynamic plan state:",
        f"- Goal: {getattr(plan, 'goal', '')}",
        f"- Status: {getattr(plan, 'status', '')}",
        f"- Current step: {current_step_id or 'none'}",
        (
            "Execution rule: work on the current in_progress step only, use other steps as context, "
            "and call runtime_plan.complete_step with evidence when the current step is satisfied."
        ),
    ]
    counts = _step_status_counts(steps)
    if counts:
        lines.append(f"- Step status counts: {_dict_summary(counts)}")
    for step in steps[:PLAN_EVIDENCE_MAX_STEPS]:
        step_id = getattr(step, "step_id", "")
        marker = " <= current" if current_step_id and step_id == current_step_id else ""
        lines.append(
            "- "
            + f"{step_id}: {getattr(step, 'status', '')}{marker}; "
            + f"{getattr(step, 'title', '')}; {getattr(step, 'objective', '')}"
        )
        is_current = bool(current_step_id and step_id == current_step_id)
        if is_current:
            acceptance = _short_list(getattr(step, "acceptance_criteria", None), limit=3)
            if acceptance:
                lines.append(f"  acceptance: {acceptance}")
            tool_hints = _short_list(getattr(step, "tool_hints", None), limit=6)
            if tool_hints:
                lines.append(f"  tool_hints: {tool_hints}")
        result = getattr(step, "result_summary", None)
        if result:
            lines.append(f"  result: {_truncate_text(result, PLAN_RESULT_SUMMARY_MAX_CHARS)}")
        evidence = _evidence_summary(getattr(step, "evidence", None), limit=4 if is_current else 2)
        if evidence:
            lines.append(f"  evidence: {evidence}")
    if len(steps) > PLAN_EVIDENCE_MAX_STEPS:
        lines.append(f"- Additional steps omitted from prompt context: {len(steps) - PLAN_EVIDENCE_MAX_STEPS}")
    last_execution = getattr(plan, "last_execution", None)
    if isinstance(last_execution, dict):
        last_summary = _last_execution_summary(last_execution)
        if last_summary:
            lines.append(f"- Last execution: {last_summary}")
    return "\n".join(line for line in lines if line.strip())


def _step_status_counts(steps: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for step in steps:
        status = str(getattr(step, "status", "") or "").strip()
        if status:
            counts[status] = counts.get(status, 0) + 1
    return counts


def _dict_summary(value: dict[str, int]) -> str:
    return ", ".join(f"{key}={value[key]}" for key in sorted(value))


def _short_list(value: Any, *, limit: int) -> str:
    if not isinstance(value, list):
        return ""
    items = [_truncate_text(str(item).strip(), PLAN_EVIDENCE_VALUE_MAX_CHARS) for item in value if str(item).strip()]
    if not items:
        return ""
    shown = items[:limit]
    suffix = f"; +{len(items) - limit} more" if len(items) > limit else ""
    return "; ".join(shown) + suffix


def _evidence_summary(value: Any, *, limit: int) -> str:
    if not isinstance(value, list):
        return ""
    items: list[str] = []
    for item in value:
        summary = _evidence_item_summary(item)
        if summary:
            items.append(summary)
    if not items:
        return ""
    shown = items[:limit]
    suffix = f"; +{len(items) - limit} more" if len(items) > limit else ""
    return "; ".join(shown) + suffix


def _evidence_item_summary(item: Any) -> str:
    if not isinstance(item, dict):
        return _truncate_text(str(item).strip(), PLAN_EVIDENCE_VALUE_MAX_CHARS)
    candidates = [
        _path_like_value(item.get("path")),
        _path_like_value(item.get("file_path")),
        _path_like_value(item.get("output_path")),
        _path_like_value(item.get("report_path")),
        _path_like_value(item.get("artifact_path")),
    ]
    output = item.get("output")
    if isinstance(output, dict):
        candidates.extend(
            [
                _path_like_value(output.get("path")),
                _path_like_value(output.get("file_path")),
                _path_like_value(output.get("output_path")),
                _path_like_value(output.get("report_path")),
                _path_like_value(output.get("artifact_path")),
            ]
        )
    message = str(item.get("message") or "").strip()
    candidates.append(message)
    for candidate in candidates:
        if candidate:
            return _truncate_text(candidate, PLAN_EVIDENCE_VALUE_MAX_CHARS)
    return _truncate_text(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str), PLAN_EVIDENCE_VALUE_MAX_CHARS)


def _path_like_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text


def _last_execution_summary(value: dict[str, Any]) -> str:
    parts: list[str] = []
    step_id = str(value.get("step_id") or "").strip()
    status = str(value.get("status") or "").strip()
    result = str(value.get("result_summary") or "").strip()
    if step_id:
        parts.append(f"step_id={step_id}")
    if status:
        parts.append(f"status={status}")
    if result:
        parts.append(f"result={_truncate_text(result, PLAN_RESULT_SUMMARY_MAX_CHARS)}")
    evidence = _evidence_summary(value.get("evidence"), limit=2)
    if evidence:
        parts.append(f"evidence={evidence}")
    return "; ".join(parts)


def _truncate_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 14)].rstrip() + "...[truncated]"


