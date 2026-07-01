from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from web_frontend.backend.runtime_bridge import RuntimeBridge
from web_frontend.backend.routes.utils import optional_package, resource_command


def create_knowledge_router(runtime_bridge: RuntimeBridge) -> APIRouter:
    router = APIRouter(prefix="/api/knowledge")

    @router.get("/sources")
    async def list_knowledge_sources(package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {"action": "list_sources", **optional_package(package_id)},
            {"knowledge_sources_listed"},
        )
        return {"event": event}

    @router.post("/sources")
    async def create_knowledge_source(payload: dict[str, Any]):
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {"action": "confirm_source", **payload},
            {"knowledge_source_registered"},
            timeout_seconds=120.0,
        )
        return {"event": event}

    @router.delete("/sources/{source_id}")
    async def delete_knowledge_source(source_id: str, package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {"action": "remove_source", "source_id": source_id, **optional_package(package_id)},
            {"knowledge_source_removed"},
        )
        return {"event": event}

    @router.post("/sources/{source_id}/reindex")
    async def reindex_knowledge_source(source_id: str, package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {"action": "reindex", "source_id": source_id, **optional_package(package_id)},
            {"knowledge_source_reindex_requested"},
            timeout_seconds=120.0,
        )
        return {"event": event}

    @router.get("/documents")
    async def list_knowledge_documents(source_id: str, package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {"action": "list_documents", "source_id": source_id, **optional_package(package_id)},
            {"knowledge_documents_listed"},
        )
        return {"event": event}

    @router.get("/search")
    async def search_knowledge(
        query: str,
        source_id: str | None = None,
        package_id: str | None = None,
    ):
        payload = {"action": "search", "query": query, **optional_package(package_id)}
        if source_id:
            payload["source_id"] = source_id
        event = await resource_command(runtime_bridge, "knowledge_manage", payload, {"knowledge_search_completed"})
        return {"event": event}

    @router.get("/document")
    async def read_knowledge_document(document_id: str, package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "knowledge_manage",
            {"action": "read", "document_id": document_id, **optional_package(package_id)},
            {"knowledge_document_read"},
        )
        return {"event": event}

    return router
