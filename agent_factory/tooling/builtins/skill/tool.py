from __future__ import annotations

from typing import Any

from agent_factory.dynamic_runtime.skill_runtime import SnapshotSkillRuntime
from agent_factory.tooling.builtins.skill.specs import SKILL_RUNTIME_RESOURCE
from agent_factory.tooling.envelope import tool_envelope


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = resources.get(SKILL_RUNTIME_RESOURCE)
    if not isinstance(runtime, SnapshotSkillRuntime):
        raise RuntimeError("Skill runtime is not configured")
    action = str(arguments.get("action") or "").strip()
    if action == "list":
        output = {"action": action, "skills": runtime.list()}
    elif action == "describe":
        output = {"action": action, "skill": runtime.describe(_required(arguments, "name"))}
    elif action == "load":
        output = {"action": action, "skill": runtime.load(_required(arguments, "name"), reason=_required(arguments, "reason"))}
    elif action == "read_resource":
        output = {"action": action, "resource": runtime.read_resource(_required(arguments, "name"), path=_required(arguments, "path"))}
    else:
        raise ValueError("Skill action must be list, describe, load, or read_resource")
    return tool_envelope(output, summary=f"skill {action} completed")


def _required(arguments: dict[str, Any], name: str) -> str:
    value = str(arguments.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value
