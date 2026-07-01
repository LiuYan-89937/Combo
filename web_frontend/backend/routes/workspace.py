from __future__ import annotations

from fastapi import APIRouter, Query

from web_frontend.backend.runtime_bridge import RuntimeBridge
from web_frontend.backend.routes.utils import optional_package, resource_command


def create_workspace_router(runtime_bridge: RuntimeBridge) -> APIRouter:
    router = APIRouter(prefix="/api/workspace")

    @router.get("/roots")
    async def workspace_roots(package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "workspace_manage",
            {"action": "roots", **optional_package(package_id)},
            {"workspace_roots_listed"},
        )
        return {"event": event}

    @router.get("/entries")
    async def workspace_entries(
        scope: str = "workdir",
        path: str = "",
        package_id: str | None = None,
    ):
        event = await resource_command(
            runtime_bridge,
            "workspace_manage",
            {"action": "list", "scope": scope, "path": path, **optional_package(package_id)},
            {"workspace_entries_listed"},
        )
        return {"event": event}

    @router.get("/file")
    async def workspace_file(
        scope: str = "workdir",
        path: str = "",
        max_chars: int = Query(default=120000, ge=1000, le=200000),
        package_id: str | None = None,
    ):
        event = await resource_command(
            runtime_bridge,
            "workspace_manage",
            {
                "action": "read",
                "scope": scope,
                "path": path,
                "max_chars": max_chars,
                **optional_package(package_id),
            },
            {"workspace_file_read"},
        )
        return {"event": event}

    return router
