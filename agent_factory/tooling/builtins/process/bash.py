from __future__ import annotations

import shlex
from typing import Any

from agent_factory.tooling.builtins.process.manager import (
    PROCESS_MANAGER,
    output_limit,
    process_runtime_boundary,
    required_string,
    resolve_cwd,
    wait_seconds,
)
from agent_factory.tooling.spec import ToolRiskResult


HIGH_RISK_COMMANDS = {"rm", "dd", "mkfs", "sudo", "chmod", "chown", "curl", "wget", "scp", "ssh"}
SHELL_CONTROL_TOKENS = ("|", "&&", "||", ";", "$(", "`", ">", "<")


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=["bash command must be a non-empty string"],
        ).model_dump(mode="json")
    cwd_result = _evaluate_cwd(arguments, context)
    if cwd_result.action == "deny":
        return cwd_result.model_dump(mode="json")
    reasons = ["bash is a high-risk tool and requires approval"]
    facts = dict(cwd_result.facts)
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[f"bash command cannot be parsed safely: {exc}"],
            facts=facts,
        ).model_dump(mode="json")
    binary = parts[0] if parts else ""
    facts["command_binary"] = binary
    facts["contains_shell_control"] = any(token in command for token in SHELL_CONTROL_TOKENS)
    if binary in HIGH_RISK_COMMANDS:
        reasons.append(f"command starts with high-risk binary: {binary}")
    if facts["contains_shell_control"]:
        reasons.append("command contains shell control structure")
    return ToolRiskResult(
        action="ask",
        risk_level="high",
        reasons=reasons,
        facts=facts,
    ).model_dump(mode="json")


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


def _evaluate_cwd(arguments: dict[str, Any], context: dict[str, Any]) -> ToolRiskResult:
    tool_resources = dict(context.get("resources") or {})
    root, allow_external = process_runtime_boundary(tool_resources)
    try:
        cwd = resolve_cwd(cwd=arguments.get("cwd"), root=root, allow_external=allow_external)
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=[f"cwd is outside the configured process runtime boundary: {exc}"],
            facts={"process_root": str(root)},
        )
    return ToolRiskResult(
        action="inherit",
        facts={
            "cwd": str(cwd),
            "process_root": str(root),
        },
    )
