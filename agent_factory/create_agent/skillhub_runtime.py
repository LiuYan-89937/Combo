from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from agent_factory.create_agent.mcp_inheritance import factory_mcp_tool_ids, materialized_package_mcp_tool_ids
from agent_factory.create_agent.model_tool_access import MODEL_CONTRACT_PATH, model_bindings_ready


_BLOCKED_ACTIONS = {"search", "install"}
_SUPPORTED_PATTERNS = {"react_agent", "plan_and_execute"}


class CreateAgentSkillHubRuntime:
    def __init__(
        self,
        *,
        runtime: Any,
        package_root: str | Path,
        on_skill_config_changed: Callable[[], None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._package_root = Path(package_root).expanduser().resolve()
        self._on_skill_config_changed = on_skill_config_changed

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip().lower()
        if action in _BLOCKED_ACTIONS:
            blocked = _precondition_failure(self._package_root, action=action)
            if blocked is not None:
                return blocked
        result = self._runtime.run(payload)
        if action in {"install", "remove"} and _skill_config_changed(result):
            self._refresh_skill_config()
        return result

    def tool_resource_summary(self) -> dict[str, Any]:
        summary = (
            self._runtime.tool_resource_summary()
            if hasattr(self._runtime, "tool_resource_summary")
            else {}
        )
        return {
            **(summary if isinstance(summary, dict) else {}),
            "mode": "create_agent_guarded",
            "package_root": str(self._package_root),
        }

    def _refresh_skill_config(self) -> None:
        if self._on_skill_config_changed is None:
            return
        self._on_skill_config_changed()


def wrap_create_agent_skillhub_runtime(
    runtime: Any,
    *,
    package_root: str | Path,
    on_skill_config_changed: Callable[[], None] | None = None,
) -> Any:
    if runtime is None:
        return None
    return CreateAgentSkillHubRuntime(
        runtime=runtime,
        package_root=package_root,
        on_skill_config_changed=on_skill_config_changed,
    )


def _skill_config_changed(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("status") != "ok":
        return False
    return bool(result.get("restart_required") or result.get("installed_skill") or result.get("removed_skill"))


def _precondition_failure(package_root: Path, *, action: str) -> dict[str, Any] | None:
    try:
        if not model_bindings_ready(package_root):
            return _blocked(
                package_root,
                action=action,
                message=(
                    "SkillHUB is blocked until model pool bindings are written. "
                    "Call model_pool_select, then create_agent_authoring(action='configure_model_bindings') first."
                ),
                missing=["model_bindings"],
                next_action={
                    "tool": "create_agent_authoring",
                    "arguments": {"action": "configure_model_bindings"},
                },
            )
    except Exception as exc:
        return _blocked(
            package_root,
            action=action,
            message=f"SkillHUB is blocked because {MODEL_CONTRACT_PATH.as_posix()} is invalid: {type(exc).__name__}: {exc}",
            missing=["valid_model_contract"],
            next_action={
                "tool": "create_agent_authoring",
                "arguments": {"action": "configure_model_bindings"},
            },
        )

    assembly_state = _assembly_state(package_root)
    if not assembly_state["configured"]:
        return _blocked(
            package_root,
            action=action,
            message=(
                "SkillHUB is blocked until pattern assembly declares runtime tool access. "
                "Configure the pattern and inherited runtime/MCP tool candidates before SkillHUB search or install."
            ),
            missing=["pattern_assembly_tool_access"],
            next_action={
                "tool": "create_agent_authoring",
                "arguments": {"action": "configure_pattern_assembly"},
            },
        )

    try:
        referenced_mcp = _referenced_factory_mcp_tool_ids(assembly_state["referenced_tool_ids"])
    except Exception as exc:
        return _blocked(
            package_root,
            action=action,
            message=f"SkillHUB is blocked because factory MCP candidates cannot be inspected: {type(exc).__name__}: {exc}",
            missing=["mcp_candidate_inspection"],
            next_action={
                "tool": "create_agent_authoring",
                "arguments": {"action": "materialize_mcp_inheritance"},
            },
        )
    if referenced_mcp:
        try:
            materialized = materialized_package_mcp_tool_ids(package_root)
        except Exception as exc:
            return _blocked(
                package_root,
                action=action,
                message=f"SkillHUB is blocked because MCP inheritance cannot be inspected: {type(exc).__name__}: {exc}",
                missing=["mcp_inheritance_inspection"],
                next_action={
                    "tool": "create_agent_authoring",
                    "arguments": {"action": "materialize_mcp_inheritance"},
                },
            )
        missing = sorted(set(referenced_mcp) - set(materialized))
        if missing:
            return _blocked(
                package_root,
                action=action,
                message=(
                    "SkillHUB is blocked until referenced factory MCP tools are inherited into this package: "
                    + ", ".join(missing)
                ),
                missing=["mcp_inheritance_materialization"],
                next_action={
                    "tool": "create_agent_authoring",
                    "arguments": {"action": "materialize_mcp_inheritance"},
                },
            )
    return None


def _blocked(
    package_root: Path,
    *,
    action: str,
    message: str,
    missing: list[str],
    next_action: dict[str, Any],
) -> dict[str, Any]:
    return {
        "action": action,
        "status": "blocked",
        "message": message,
        "cli_available": False,
        "cli_path": "",
        "cli_version": "",
        "extension_root": str(package_root / "extensions"),
        "skills_dir": str(package_root / "extensions" / "skills"),
        "items": [],
        "raw_output": "",
        "installed_skill": None,
        "restart_required": False,
        "precondition": {
            "missing": missing,
            "next_action": next_action,
        },
    }


def _assembly_state(package_root: Path) -> dict[str, Any]:
    path = package_root / "assembly_spec.json"
    if not path.is_file():
        return {"configured": False, "referenced_tool_ids": set()}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"configured": False, "referenced_tool_ids": set()}
    pattern_id = str((payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}).get("pattern_id") or "")
    bindings = payload.get("bindings") if isinstance(payload.get("bindings"), dict) else {}
    node_bindings = bindings.get("node_bindings") if isinstance(bindings.get("node_bindings"), list) else []
    tool_access_bindings = [
        item
        for item in node_bindings
        if isinstance(item, dict) and item.get("binding_type") == "tool_access"
    ]
    return {
        "configured": pattern_id in _SUPPORTED_PATTERNS and bool(tool_access_bindings),
        "referenced_tool_ids": _referenced_tool_ids(tool_access_bindings),
    }


def _referenced_tool_ids(tool_access_bindings: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for binding in tool_access_bindings:
        payload = binding.get("payload") if isinstance(binding.get("payload"), dict) else {}
        allowed = payload.get("allowed_tool_ids")
        if not isinstance(allowed, list):
            continue
        ids.update(str(item).strip() for item in allowed if str(item).strip())
    return ids


def _referenced_factory_mcp_tool_ids(referenced_tool_ids: set[str]) -> set[str]:
    if not referenced_tool_ids:
        return set()
    factory_ids = factory_mcp_tool_ids()
    return set(referenced_tool_ids) & set(factory_ids)
