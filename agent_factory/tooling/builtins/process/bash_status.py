from __future__ import annotations

from typing import Any

from agent_factory.tooling.builtins.process.manager import PROCESS_MANAGER, output_limit, required_string


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    _ = resources
    process_id = required_string(arguments, "process_id")
    return PROCESS_MANAGER.snapshot(
        process_id=process_id,
        max_output_chars=output_limit(arguments),
    )
