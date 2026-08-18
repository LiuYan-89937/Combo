from __future__ import annotations

from typing import Any

from combo.dynamic_runtime.capability_invocation_runtime import (
    BoundCapabilityInvocationRuntime,
)


CAPABILITY_INVOCATION_RUNTIME_RESOURCE = "capability_invocation_runtime"


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = resources.get(CAPABILITY_INVOCATION_RUNTIME_RESOURCE)
    if not isinstance(runtime, BoundCapabilityInvocationRuntime):
        raise RuntimeError("capability invocation runtime is not configured")
    target_arguments = arguments.get("arguments")
    if not isinstance(target_arguments, dict):
        raise ValueError("target arguments must be an object")
    return runtime.invoke(
        name=str(arguments.get("name") or ""),
        kind=str(arguments.get("kind") or ""),
        server_name=_optional_text(arguments.get("server_name")),
        arguments=dict(target_arguments),
    )


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
