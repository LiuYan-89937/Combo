from __future__ import annotations

from typing import Any

from agent_factory.tooling.builtins.process.manager import (
    PROCESS_MANAGER,
    output_limit,
    process_runtime_boundary,
    required_string,
    resolve_cwd,
    wait_seconds,
)


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    command = required_string(arguments, "command")
    mode = str(arguments.get("mode", "foreground")).strip()
    if mode not in {"foreground", "background"}:
        raise ValueError("mode must be foreground or background")
    root, allow_external = process_runtime_boundary(resources)
    cwd = resolve_cwd(cwd=arguments.get("cwd"), root=root, allow_external=allow_external)
    if not cwd.exists():
        raise FileNotFoundError(str(cwd))
    if not cwd.is_dir():
        raise NotADirectoryError(str(cwd))
    return PROCESS_MANAGER.start(
        command=command,
        cwd=cwd,
        mode=mode,
        wait_seconds=wait_seconds(arguments),
        max_output_chars=output_limit(arguments),
    )
