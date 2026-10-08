from __future__ import annotations

from typing import Any

from combo.tooling.builtins.process.manager import require_process_runtime
from combo.tooling.envelope import tool_envelope
from combo.tooling.spec import ToolRiskResult
from combo.tooling.execution_context import runtime_tool_cancellation_requested


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    _ = context
    return ToolRiskResult(action="allow", risk_level="low").model_dump(mode="json")


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = require_process_runtime(resources)
    process_id = runtime.manager.resolve_target(dict(arguments.get("process") or {}))
    return tool_envelope(
        runtime.manager.wait_snapshot(
            process_id=process_id,
            wait_seconds=float(arguments.get("wait_seconds", 0)),
            after_revision=arguments.get("after_revision"),
            cancellation_requested=runtime_tool_cancellation_requested,
        )
    )
