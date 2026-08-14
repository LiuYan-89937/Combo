from __future__ import annotations

from dataclasses import asdict
from typing import Any

from agent_factory.dynamic_runtime.control_plane_store import GlobalKnowledgeStore
from agent_factory.runtime_protocol import RuntimeExecutionIdentity
from agent_factory.tooling.builtins.knowledge.specs import (
    KNOWLEDGE_RUNTIME_RESOURCE,
    RUNTIME_IDENTITY_RESOURCE,
)
from agent_factory.tooling.envelope import tool_envelope


_READ_ACTIONS = frozenset({"list_sources", "search", "list_documents", "read"})
_WRITE_ACTIONS = frozenset({"add_text_source", "remove_source"})


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action in _READ_ACTIONS:
        return {"action": "allow", "risk_level": "low", "reasons": ["read-only knowledge operation"]}
    if action == "add_text_source":
        return {"action": "ask", "risk_level": "medium", "reasons": ["persists content in the shared knowledge base"]}
    if action == "remove_source":
        return {"action": "ask", "risk_level": "high", "reasons": ["removes a shared knowledge source"]}
    return {"action": "deny", "risk_level": "high", "reasons": ["unsupported knowledge action"]}


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    store = resources.get(KNOWLEDGE_RUNTIME_RESOURCE)
    identity = resources.get(RUNTIME_IDENTITY_RESOURCE)
    if not isinstance(store, GlobalKnowledgeStore):
        raise RuntimeError("knowledge runtime is not configured")
    _require_main(identity)
    action = str(arguments.get("action") or "").strip()
    if action == "list_sources":
        output = {"action": action, "sources": store.sources()}
    elif action == "search":
        output = {
            "action": action,
            "results": store.search(
                query=_required_text(arguments, "query"),
                limit=int(arguments["limit"]) if arguments.get("limit") is not None else None,
            ),
        }
    elif action == "list_documents":
        documents = store.documents(_required_text(arguments, "source_id"))
        output = {
            "action": action,
            "documents": [asdict(item) for item in documents],
        }
    elif action == "read":
        document = store.require_document(_required_text(arguments, "document_id"))
        output = {
            "action": action,
            "document": asdict(document),
        }
    elif action == "add_text_source":
        name = _required_text(arguments, "display_name")
        source = store.create_source(
            {"display_name": name, "kind": "note"},
            [{
                "title": name,
                "mime_type": str(arguments.get("mime_type") or "text/plain"),
                "content": _required_text(arguments, "content"),
            }],
        )
        output = {"action": action, "source": source}
    elif action == "remove_source":
        source_id = _required_text(arguments, "source_id")
        store.delete_source(source_id)
        output = {"action": action, "source_id": source_id, "removed": True}
    else:
        raise ValueError(f"unsupported knowledge action: {action}")
    return tool_envelope(output, summary=f"knowledge {action} completed")


def _require_main(identity: Any) -> RuntimeExecutionIdentity:
    if not isinstance(identity, RuntimeExecutionIdentity) or identity.runtime_role != "main":
        raise PermissionError("knowledge management is available only to the main Agent")
    return identity


def _required_text(arguments: dict[str, Any], name: str) -> str:
    value = str(arguments.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value
