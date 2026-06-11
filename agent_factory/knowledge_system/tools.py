from __future__ import annotations

from typing import Any

from agent_factory.knowledge_system.runtime import KnowledgeRuntime
from agent_factory.tooling.envelope import tool_envelope


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = resources.get("knowledge_runtime")
    if not isinstance(runtime, KnowledgeRuntime):
        return tool_envelope({"status": "failed", "error": "knowledge runtime is not configured"})
    action = str(arguments.get("action") or "").strip()
    try:
        if action == "list_sources":
            return tool_envelope({
                "status": "completed",
                "sources": [source.model_dump(mode="json") for source in runtime.list_sources()],
            })
        if action == "describe_source":
            return tool_envelope({"status": "completed", **runtime.describe_source(_source_id(arguments))})
        if action == "prepare_source":
            preview = runtime.prepare_source(_source_payload(arguments))
            return tool_envelope({"status": "completed", "preview": preview.model_dump(mode="json")})
        if action == "confirm_source":
            job = runtime.confirm_source(_source_payload(arguments))
            return tool_envelope({"status": "completed", "job": job.model_dump(mode="json")})
        if action == "list_documents":
            return tool_envelope({
                "status": "completed",
                "documents": [
                    document.model_dump(mode="json")
                    for document in runtime.list_documents(arguments.get("source_id"))
                ],
            })
        if action == "search":
            results = runtime.search(
                query=str(arguments.get("query") or ""),
                source_id=arguments.get("source_id"),
                mode=str(arguments.get("mode") or "auto"),
                top_k=int(arguments.get("top_k") or 8),
            )
            return tool_envelope({"status": "completed", "results": [result.model_dump(mode="json") for result in results]})
        if action == "open":
            return tool_envelope({
                "status": "completed",
                **runtime.open(
                    source_id=arguments.get("source_id"),
                    document_id=arguments.get("document_id"),
                    chunk_id=arguments.get("chunk_id"),
                ),
            })
        if action == "read":
            return tool_envelope({
                "status": "completed",
                **runtime.read(
                    document_id=arguments.get("document_id"),
                    chunk_id=arguments.get("chunk_id"),
                ),
            })
        if action == "reindex":
            job = runtime.reindex_source(_source_id(arguments))
            return tool_envelope({"status": "completed", "job": job.model_dump(mode="json")})
        if action == "remove_source":
            return tool_envelope({"status": "completed", "removed": runtime.remove_source(_source_id(arguments))})
    except Exception as exc:
        return tool_envelope({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    return tool_envelope({"status": "failed", "error": f"unsupported knowledge action: {action}"})


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action in {"list_sources", "describe_source", "list_documents", "search", "open", "read"}:
        return {"action": "allow", "risk_level": "low", "reasons": ["read-only knowledge action"]}
    if action in {"prepare_source", "confirm_source", "reindex"}:
        return {"action": "ask", "risk_level": "medium", "reasons": [f"knowledge action requires review: {action}"]}
    if action == "remove_source":
        return {"action": "ask", "risk_level": "high", "reasons": ["knowledge source removal is destructive"]}
    return {"action": "deny", "risk_level": "medium", "reasons": [f"unknown knowledge action: {action}"]}


def _source_id(arguments: dict[str, Any]) -> str:
    source_id = str(arguments.get("source_id") or "").strip()
    if not source_id:
        raise ValueError("knowledge action requires source_id")
    return source_id


def _source_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    source = arguments.get("source")
    if not isinstance(source, dict):
        raise ValueError("knowledge action requires source object")
    return dict(source)
