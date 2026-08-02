from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_factory.collaboration_system.background_task_contract import normalize_background_task_metadata
from agent_factory.collaboration_system.capacity import normalize_max_parallel_sub_agents
from agent_factory.collaboration_system.result_delivery import DELIVERY_PROTOCOL
from agent_factory.collaboration_system.store import CollaborationStore


@dataclass(frozen=True, slots=True)
class ParentAgentContext:
    package_id: str
    session_id: str
    workspace_root: Path


def parent_agent_context(resources: dict[str, Any], *, tool_id: str) -> ParentAgentContext:
    runtime_config = resources.get("runtime_execution_config")
    identity = runtime_config.get("identity") if isinstance(runtime_config, dict) else None
    if not isinstance(identity, dict):
        raise ValueError(f"{tool_id} requires runtime identity")
    package_id = _required_text(identity, "agent_id")
    session_id = _required_text(identity, "session_id")
    workspace_root = Path(_required_text(resources, "workdir_root")).expanduser().resolve()
    if not workspace_root.is_dir() or workspace_root == Path(workspace_root.anchor):
        raise ValueError(f"{tool_id} requires a valid parent workspace")
    return ParentAgentContext(
        package_id=package_id,
        session_id=session_id,
        workspace_root=workspace_root,
    )


def create_parent_controlled_session(
    store: CollaborationStore,
    resources: dict[str, Any],
    *,
    title: str,
    tool_id: str,
    task_kind: str,
    context: ParentAgentContext | None = None,
) -> tuple[dict[str, Any], ParentAgentContext]:
    context = context or parent_agent_context(resources, tool_id=tool_id)
    runtime_config = resources.get("runtime_execution_config")
    user_config = runtime_config.get("user_config") if isinstance(runtime_config, dict) else None
    max_parallel_sub_agents = normalize_max_parallel_sub_agents(
        user_config.get("max_parallel_sub_agents") if isinstance(user_config, dict) else None
    )
    session = store.create_session(
        title=title,
        main_agent_package_id=context.package_id,
        approval_mode="main_agent_delegated",
    )
    collaboration_id = str(session["collaboration_id"])
    session = store.update_session(
        collaboration_id,
        {
            "main_agent_package_session_id": context.session_id,
            "execution_config": {
                "controller": "parent_session",
                "parent_workspace_root": str(context.workspace_root),
                "delivery_protocol": DELIVERY_PROTOCOL,
                "max_parallel_sub_agents": max_parallel_sub_agents,
                "background_task": normalize_background_task_metadata({
                    "id": collaboration_id,
                    "kind": task_kind,
                    "source_tool": tool_id,
                }),
            },
        },
    )
    return session, context


def parent_workspace_root(session: dict[str, Any]) -> Path | None:
    execution_config = session.get("execution_config")
    if not isinstance(execution_config, dict):
        return None
    value = str(execution_config.get("parent_workspace_root") or "").strip()
    if not value:
        return None
    root = Path(value).expanduser().resolve()
    if not root.is_dir() or root == Path(root.anchor):
        raise ValueError(f"invalid parent collaboration workspace: {root}")
    return root


def require_parent_owned_session(
    store: CollaborationStore,
    resources: dict[str, Any],
    collaboration_id: str,
    *,
    tool_id: str,
) -> dict[str, Any]:
    parent = parent_agent_context(resources, tool_id=tool_id)
    session = store.get_session(collaboration_id)
    owner_session_id = str(session.get("main_agent_package_session_id") or "").strip()
    if owner_session_id != parent.session_id:
        raise PermissionError(f"{tool_id} cannot access a background task from another conversation")
    return session


def _required_text(values: dict[str, Any], key: str) -> str:
    text = str(values.get(key) or "").strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text
