from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool


def bind_tools(model: Any, tools: list[BaseTool]) -> Any:
    if not tools:
        return model
    return model.bind_tools(tools, tool_choice="auto")


def tool_calls_from_response(response: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, candidate in enumerate(_response_candidates(response)):
        call = _normalize_candidate(candidate, index=index)
        if call is None:
            continue
        matching_index = _matching_index(normalized, call)
        if matching_index is None:
            normalized.append(call)
        else:
            normalized[matching_index] = _merge_call(normalized[matching_index], call)
    return normalized


def _response_candidates(response: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    additional = getattr(response, "additional_kwargs", None)
    sources = [
        getattr(response, "tool_calls", None),
        getattr(response, "invalid_tool_calls", None),
        getattr(response, "tool_call_chunks", None),
    ]
    if isinstance(additional, dict):
        sources.extend(additional.get(key) for key in ("tool_calls", "invalid_tool_calls", "tool_call_chunks"))
    for value in sources:
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
    content = getattr(response, "content", None)
    if isinstance(content, list):
        candidates.extend(
            {
                "name": item.get("name"),
                "args": item.get("input"),
                "id": item.get("id"),
                "type": "tool_call",
            }
            for item in content
            if isinstance(item, dict) and str(item.get("type") or "").strip() == "tool_use"
        )
    return candidates


def _normalize_candidate(candidate: dict[str, Any], *, index: int) -> dict[str, Any] | None:
    function = candidate.get("function") if isinstance(candidate.get("function"), dict) else {}
    name = str(candidate.get("name") or function.get("name") or "").strip()
    if not name:
        return None
    arguments = next(
        (
            value
            for value in (
                candidate.get("args"),
                function.get("arguments"),
                candidate.get("arguments"),
                candidate.get("input"),
            )
            if value is not None and (not isinstance(value, str) or value.strip())
        ),
        None,
    )
    return {
        "name": name,
        "args": _arguments_object(arguments),
        "id": str(candidate.get("id") or candidate.get("tool_call_id") or f"call_{index}_{name}"),
        "type": "tool_call",
    }


def _arguments_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _matching_index(calls: list[dict[str, Any]], incoming: dict[str, Any]) -> int | None:
    call_id = str(incoming.get("id") or "")
    if call_id:
        for index, existing in enumerate(calls):
            if str(existing.get("id") or "") == call_id:
                return index
    name = str(incoming.get("name") or "")
    for index, existing in enumerate(calls):
        if str(existing.get("name") or "") == name and not existing.get("args"):
            return index
    return None


def _merge_call(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing_arguments = existing.get("args") if isinstance(existing.get("args"), dict) else {}
    incoming_arguments = incoming.get("args") if isinstance(incoming.get("args"), dict) else {}
    return {
        "name": str(existing.get("name") or incoming.get("name") or ""),
        "args": incoming_arguments or existing_arguments,
        "id": str(existing.get("id") or incoming.get("id") or ""),
        "type": "tool_call",
    }
