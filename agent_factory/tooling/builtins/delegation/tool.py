from __future__ import annotations

from typing import Any, cast

from agent_factory.dynamic_runtime.delegation_runtime import (
    BoundDelegationRuntime,
    DelegationRequest,
)
from agent_factory.runtime_protocol import ExecutionStrategy
from agent_factory.tooling.builtins.delegation.specs import DELEGATION_RUNTIME_RESOURCE
from agent_factory.tooling.envelope import tool_envelope


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = resources.get(DELEGATION_RUNTIME_RESOURCE)
    if not isinstance(runtime, BoundDelegationRuntime):
        raise RuntimeError("delegate tool requires a bound delegation runtime")
    result = runtime.delegate(
        DelegationRequest(
            strategy=_strategy(arguments.get("strategy")),
            system_prompt=_required_text(arguments.get("system_prompt"), "system_prompt"),
            objective=_required_text(arguments.get("objective"), "objective"),
            capability_names=_text_tuple(arguments.get("capabilities")),
            acceptance_criteria=_text_tuple(arguments.get("acceptance_criteria")),
        )
    )
    return tool_envelope(result, summary=f"delegated task {result['status']}")


def status(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = resources.get(DELEGATION_RUNTIME_RESOURCE)
    if not isinstance(runtime, BoundDelegationRuntime):
        raise RuntimeError("delegation status requires a bound delegation runtime")
    del arguments
    result = runtime.status()
    return tool_envelope(result, summary=f"inspected {len(result['tasks'])} delegated task(s)")


def _text_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("delegate list fields must be arrays")
    normalized = tuple(dict.fromkeys(str(item or "").strip() for item in value))
    if any(not item for item in normalized):
        raise ValueError("delegate list values must not be empty")
    return normalized


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _strategy(value: Any) -> ExecutionStrategy:
    strategy = _required_text(value, "strategy")
    if strategy not in {"react", "plan_and_execute"}:
        raise ValueError("strategy must be react or plan_and_execute")
    return cast(ExecutionStrategy, strategy)
