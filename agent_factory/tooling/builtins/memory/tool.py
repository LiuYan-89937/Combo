from __future__ import annotations

from typing import Any

from agent_factory.dynamic_runtime.memory_store import ScopedMemoryStore
from agent_factory.runtime_protocol import MemoryKind, MemoryScope, RuntimeExecutionIdentity
from agent_factory.tooling.builtins.memory.specs import (
    MEMORY_STORE_RESOURCE,
    RUNTIME_IDENTITY_RESOURCE,
)
from agent_factory.tooling.envelope import tool_envelope


_READ_ACTIONS = frozenset({"search", "list"})
_MUTATION_ACTIONS = frozenset({"write", "delete"})


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    resources = context.get("resources")
    identity = resources.get(RUNTIME_IDENTITY_RESOURCE) if isinstance(resources, dict) else None
    runtime_role = identity.get("runtime_role") if isinstance(identity, dict) else None
    if action in _READ_ACTIONS:
        return {
            "action": "allow",
            "risk_level": "low",
            "reasons": ["memory operation is read-only"],
        }
    if action in _MUTATION_ACTIONS and runtime_role == "temporary":
        return {
            "action": "deny",
            "risk_level": "high",
            "reasons": ["temporary runtimes cannot mutate long-term memory"],
        }
    if action == "write" and isinstance(identity, dict) and not identity.get("memory_agent_write_enabled", True):
        return {
            "action": "deny",
            "risk_level": "medium",
            "reasons": ["proactive memory writes are disabled in runtime preferences"],
        }
    if action == "write":
        return {
            "action": "ask",
            "risk_level": "medium",
            "reasons": ["operation persists cross-session memory"],
        }
    if action == "delete":
        return {
            "action": "ask",
            "risk_level": "high",
            "reasons": ["operation creates a deleted memory revision"],
        }
    return {
        "action": "deny",
        "risk_level": "high",
        "reasons": ["unknown memory operation"],
    }


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    store = resources.get(MEMORY_STORE_RESOURCE)
    identity = resources.get(RUNTIME_IDENTITY_RESOURCE)
    if not isinstance(store, ScopedMemoryStore):
        raise RuntimeError("memory store is not configured")
    if not isinstance(identity, RuntimeExecutionIdentity):
        raise RuntimeError("memory tool requires an owned runtime execution identity")
    action = str(arguments.get("action") or "").strip()
    if action == "search":
        results = store.search(
            principal_id=identity.principal_id,
            workspace_id=identity.workspace_id,
            query=_required_text(arguments, "query"),
            limit=int(arguments.get("limit", 20)),
        )
        output = {
            "action": action,
            "memories": [
                {
                    **item.revision.model_dump(mode="json"),
                    "score": item.score,
                }
                for item in results
            ],
        }
    elif action == "list":
        raw_scope = arguments.get("scope")
        scope: MemoryScope | None = None if raw_scope is None else _memory_scope(raw_scope)
        revisions = store.list_active(
            principal_id=identity.principal_id,
            workspace_id=identity.workspace_id,
            scope=scope,
            limit=int(arguments.get("limit", 20)),
        )
        output = {
            "action": action,
            "memories": [item.model_dump(mode="json") for item in revisions],
        }
    elif action == "write":
        _require_main(identity)
        if not identity.memory_agent_write_enabled:
            raise PermissionError("proactive memory writes are disabled in runtime preferences")
        scope = _memory_scope(arguments.get("scope"))
        revision = store.write(
            principal_id=identity.principal_id,
            scope=scope,
            workspace_id=identity.workspace_id if scope == "workspace" else None,
            kind=_memory_kind(arguments.get("kind")),
            content=_required_text(arguments, "content"),
            confidence=float(arguments.get("confidence", 1)),
            source_session_id=identity.session_id,
            source_turn_id=identity.turn_id,
            runtime_instance_id=identity.runtime_instance_id,
        )
        output = {"action": action, "memory": revision.model_dump(mode="json")}
    elif action == "delete":
        _require_main(identity)
        revision = store.delete(
            memory_id=_required_text(arguments, "memory_id"),
            principal_id=identity.principal_id,
            runtime_instance_id=identity.runtime_instance_id,
            source_session_id=identity.session_id,
            source_turn_id=identity.turn_id,
            expected_revision=int(arguments["expected_revision"]),
        )
        output = {"action": action, "memory": revision.model_dump(mode="json")}
    else:
        raise ValueError("memory action must be search, list, write, or delete")
    return tool_envelope(output, summary=f"memory {action} completed")


def _require_main(identity: RuntimeExecutionIdentity) -> None:
    if identity.runtime_role != "main":
        raise PermissionError("temporary runtimes cannot mutate long-term memory")


def _required_text(arguments: dict[str, Any], name: str) -> str:
    value = str(arguments.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _memory_scope(value: Any) -> MemoryScope:
    if value not in {"user", "workspace"}:
        raise ValueError("memory scope must be user or workspace")
    return value


def _memory_kind(value: Any) -> MemoryKind:
    if value not in {"constraint", "preference", "decision", "fact", "artifact"}:
        raise ValueError("unsupported memory kind")
    return value
