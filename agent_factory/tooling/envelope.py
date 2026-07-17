from __future__ import annotations

from typing import Any


TOOL_ENVELOPE_VERSION = "tool_execution_envelope.v0"
RUNTIME_CONTROL_EVIDENCE_KEY = "runtime_control"
RUNTIME_CONTROL_WAIT_ACTION = "wait"


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


def runtime_wait_evidence(*, status: str, reason: str, message: str | None = None) -> dict[str, Any]:
    clean_status = str(status or "").strip()
    clean_reason = str(reason or "").strip()
    if not clean_status:
        raise ValueError("runtime wait status is required")
    if not clean_reason:
        raise ValueError("runtime wait reason is required")
    control = {
        "action": RUNTIME_CONTROL_WAIT_ACTION,
        "status": clean_status,
        "reason": clean_reason,
    }
    clean_message = str(message or "").strip()
    if clean_message:
        control["message"] = clean_message
    return {
        RUNTIME_CONTROL_EVIDENCE_KEY: {
            **control,
        }
    }


def runtime_wait_control(observations: list[dict[str, Any]]) -> dict[str, str] | None:
    controls: list[dict[str, str]] = []
    for observation in observations:
        evidence = observation.get("evidence") if isinstance(observation, dict) else None
        control = evidence.get(RUNTIME_CONTROL_EVIDENCE_KEY) if isinstance(evidence, dict) else None
        if not isinstance(control, dict) or str(control.get("action") or "").strip() != RUNTIME_CONTROL_WAIT_ACTION:
            continue
        status = str(control.get("status") or "").strip()
        reason = str(control.get("reason") or "").strip()
        message = str(control.get("message") or "").strip()
        if status and reason:
            controls.append({"status": status, "reason": reason, "message": message})
    if not controls:
        return None
    statuses = {item["status"] for item in controls}
    if len(statuses) != 1:
        raise ValueError(f"conflicting runtime wait statuses: {sorted(statuses)}")
    return controls[-1]
