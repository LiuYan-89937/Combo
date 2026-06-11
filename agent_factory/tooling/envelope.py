from __future__ import annotations

from typing import Any


TOOL_ENVELOPE_VERSION = "tool_execution_envelope.v0"


def tool_envelope(
    output: dict[str, Any] | None = None,
    *,
    evidence: dict[str, Any] | None = None,
    summary: str = "",
) -> dict[str, Any]:
    return {
        "version": TOOL_ENVELOPE_VERSION,
        "output": dict(output or {}),
        "evidence": dict(evidence or {}),
        "summary": summary,
    }


def is_tool_envelope(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("version") == TOOL_ENVELOPE_VERSION
        and isinstance(value.get("output"), dict)
    )


def unpack_tool_envelope(value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
    if not is_tool_envelope(value):
        raise ValueError("tool entrypoint must return tool_execution_envelope.v0")
    evidence = value.get("evidence")
    return (
        dict(value.get("output") or {}),
        dict(evidence) if isinstance(evidence, dict) else {},
        str(value.get("summary") or "").strip(),
    )
