from __future__ import annotations

from dataclasses import asdict
from typing import Any

from combo.runtime_protocol import RuntimeExecutionIdentity
from combo.tooling.builtins.runtime_ports import KnowledgeRuntimePort
from combo.tooling.builtins.knowledge.specs import (
    KNOWLEDGE_RUNTIME_RESOURCE,
    RUNTIME_IDENTITY_RESOURCE,
)
from combo.tooling.envelope import tool_envelope
from combo.tooling.targets import select_target


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
    if not isinstance(store, KnowledgeRuntimePort):
        raise RuntimeError("knowledge runtime is not configured")
    _require_main(identity)
    action = str(arguments.get("action") or "").strip()
    if action == "list_sources":
        output = {"action": action, "sources": [_public_source(item) for item in store.sources()]}
    elif action == "search":
        results = store.search(
            query=_required_text(arguments, "query"),
            limit=int(arguments["limit"]) if arguments.get("limit") is not None else None,
        )
        documents = {item["document_id"]: item for item in store.document_catalog()}
        output = {
            "action": action,
            "results": [_public_search_result(item, documents[item["document_id"]]) for item in results if item["document_id"] in documents],
        }
    elif action == "list_documents":
        source = _source(store, arguments["source"])
        documents = store.documents(str(source["source_id"]))
        output = {
            "action": action,
            "documents": [_public_document(item, source["display_name"]) for item in documents],
        }
    elif action == "read":
        target = select_target(
            store.document_catalog(), selector=arguments["document"], kind="knowledge document",
            describe=lambda item: {key: item[key] for key in ("title", "source", "created_at")},
        )
        document = store.require_document(str(target["document_id"]))
        output = {
            "action": action,
            "document": _public_document(document, target["source"]),
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
        output = {"action": action, "source": _public_source(source)}
    elif action == "remove_source":
        source = _source(store, arguments["source"])
        store.delete_source(str(source["source_id"]))
        output = {"action": action, "source": _source_target(source), "removed": True}
    else:
        raise ValueError(f"unsupported knowledge action: {action}")
    return tool_envelope(output, summary=f"knowledge {action} completed")


def _source_target(source: dict[str, Any]) -> dict[str, Any]:
    return {"name": source["display_name"], "created_at": source["created_at"]}


def _source(store: KnowledgeRuntimePort, selector: dict[str, Any]) -> dict[str, Any]:
    return select_target(store.sources(), selector=selector, describe=_source_target, kind="knowledge source")


def _public_source(source: dict[str, Any]) -> dict[str, Any]:
    return {"name": source["display_name"], **{key: value for key, value in source.items() if key not in {"source_id", "display_name"}}}


def _public_document(document: Any, source_name: str) -> dict[str, Any]:
    return {"source": source_name, **{key: value for key, value in asdict(document).items() if key not in {"source_id", "document_id"}}}


def _public_search_result(result: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in result.items() if key not in {"source_id", "document_id", "chunk_id"}},
        "source": document["source"], "title": document["title"], "created_at": document["created_at"],
    }


def _require_main(identity: Any) -> RuntimeExecutionIdentity:
    if not isinstance(identity, RuntimeExecutionIdentity) or identity.runtime_role != "main":
        raise PermissionError("knowledge management is available only to the main Agent")
    return identity


def _required_text(arguments: dict[str, Any], name: str) -> str:
    value = str(arguments.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value
