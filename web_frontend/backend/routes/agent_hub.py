from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import (
    AgentPackageRuntimeManager,
)
from web_frontend.backend.agent_hub_client import AgentHubClient, AgentHubClientError


def create_agent_hub_router(
    *,
    client: AgentHubClient | None = None,
    runtime_factory: Callable[[], AgentPackageRuntimeManager] | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/agent-hub")
    hub = client or AgentHubClient()
    resolve_runtime = runtime_factory or AgentPackageRuntimeManager

    @router.get("/auth")
    async def auth_status():
        return await _call(hub.auth_status)

    @router.post("/auth/browser/start")
    async def start_browser_login():
        return await _call(hub.start_browser_login)

    @router.post("/auth/browser/poll")
    async def poll_browser_login(payload: dict[str, Any]):
        flow_id = str(payload.get("flow_id") or "").strip()
        poll_secret = str(payload.get("poll_secret") or "").strip()
        if not flow_id or not poll_secret:
            raise HTTPException(status_code=422, detail="browser login flow is required")
        return await _call(
            hub.poll_browser_login,
            flow_id=flow_id,
            poll_secret=poll_secret,
        )

    @router.post("/auth/browser/cancel")
    async def cancel_browser_login(payload: dict[str, Any]):
        flow_id = str(payload.get("flow_id") or "").strip()
        poll_secret = str(payload.get("poll_secret") or "").strip()
        if flow_id and poll_secret:
            await _call(
                hub.cancel_browser_login,
                flow_id=flow_id,
                poll_secret=poll_secret,
            )
        return {"status": "cancelled"}

    @router.post("/auth/logout")
    async def logout():
        return await _call(hub.logout)

    @router.get("/packages")
    async def list_packages(
        q: str = Query(default="", max_length=200),
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return await _call(hub.list_packages, query=q, limit=limit, offset=offset)

    @router.get("/packages/{publisher}/{package_id}")
    async def package_detail(publisher: str, package_id: str):
        return await _call(hub.package_detail, publisher, package_id)

    @router.get("/uploads")
    async def list_uploads(limit: int = Query(default=50, ge=1, le=100)):
        return await _call(hub.list_uploads, limit=limit)

    @router.post("/packages/{package_id}/publish")
    async def publish_package(package_id: str):
        return await _call(
            hub.publish_package,
            package_id,
            runtime=resolve_runtime(),
        )

    @router.post("/releases/{release_id}/install")
    async def install_release(release_id: str, payload: dict[str, Any] | None = None):
        return await _call(
            hub.install_release,
            release_id,
            replace=bool((payload or {}).get("replace")),
            runtime=resolve_runtime(),
        )

    return router


async def _call(function, *args, **kwargs):
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    except AgentHubClientError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except FileExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "package_already_installed", "message": str(exc)},
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
