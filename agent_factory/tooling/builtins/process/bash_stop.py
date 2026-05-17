from __future__ import annotations

from typing import Any

from agent_factory.tooling.builtins.process.manager import (
    PROCESS_MANAGER,
    bounded_int,
    output_limit,
    required_string,
)


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    _ = resources
    process_id = required_string(arguments, "process_id")
    grace_seconds = bounded_int(arguments, "grace_seconds", default=2, minimum=0, maximum=300)
    return PROCESS_MANAGER.stop(
        process_id=process_id,
        grace_seconds=grace_seconds,
        max_output_chars=output_limit(arguments),
    )
