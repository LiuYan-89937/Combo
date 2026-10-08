from __future__ import annotations

from typing import Any

from combo.tooling.builtins.process.manager import (
    bounded_int,
    require_process_runtime,
)
from combo.tooling.envelope import tool_envelope
from combo.tooling.spec import ToolRiskResult


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    _ = context
    return ToolRiskResult(
        action="ask",
        risk_level="medium",
        reasons=["stopping a running process tree requires approval"],
    ).model_dump(mode="json")


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = require_process_runtime(resources)
    process_id = runtime.manager.resolve_target(dict(arguments.get("process") or {}))
    grace_seconds = bounded_int(arguments, "grace_seconds", default=2, minimum=0, maximum=300)
    return tool_envelope(
        runtime.manager.stop(
            process_id=process_id,
            grace_seconds=grace_seconds,
        )
    )
