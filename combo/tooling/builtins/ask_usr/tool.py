from __future__ import annotations

from typing import Any

from combo.tooling.envelope import tool_failure


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    del arguments, resources
    # ComboToolNode owns the interrupt so the graph can suspend and resume safely.
    return tool_failure(
        "ask_usr must be handled by the runtime interaction node",
        summary="ask_usr requires a runtime question interrupt",
        retryable=False,
    )
