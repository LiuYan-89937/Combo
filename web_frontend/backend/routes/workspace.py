from __future__ import annotations

import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.factory_graph.frontend_bridge.workspace_resources import FrontendWorkspaceService
from agent_factory.factory_graph.session import FactorySessionManager
from web_frontend.backend.runtime_bridge import RuntimeBridge
from web_frontend.backend.routes.utils import optional_package, resource_command


def create_workspace_router(runtime_bridge: RuntimeBridge) -> APIRouter:
    router = APIRouter(prefix="/api/workspace")

    @router.get("/roots")
    async def workspace_roots(
        package_id: str | None = None,
        resource_mode: str | None = None,
        factory_session_id: str | None = None,
        package_session_id: str | None = None,
        create_agent_session_id: str | None = None,
        collaboration_id: str | None = None,
    ):
        event = await resource_command(
            runtime_bridge,
            "workspace_manage",
            {
                "action": "roots",
                **workspace_context_payload(
                    package_id=package_id,
                    resource_mode=resource_mode,
                    factory_session_id=factory_session_id,
                    package_session_id=package_session_id,
                    create_agent_session_id=create_agent_session_id,
                    collaboration_id=collaboration_id,
                ),
            },
            {"workspace_roots_listed"},
        )
        return {"event": event}

    @router.get("/entries")
    async def workspace_entries(
        scope: str = "workdir",
        path: str = "",
        package_id: str | None = None,
        resource_mode: str | None = None,
        factory_session_id: str | None = None,
        package_session_id: str | None = None,
        create_agent_session_id: str | None = None,
        collaboration_id: str | None = None,
    ):
        event = await resource_command(
            runtime_bridge,
            "workspace_manage",
            {
                "action": "list",
                "scope": scope,
                "path": path,
                **workspace_context_payload(
                    package_id=package_id,
                    resource_mode=resource_mode,
                    factory_session_id=factory_session_id,
                    package_session_id=package_session_id,
                    create_agent_session_id=create_agent_session_id,
                    collaboration_id=collaboration_id,
                ),
            },
            {"workspace_entries_listed"},
        )
        return {"event": event}

    @router.get("/file")
    async def workspace_file(
        scope: str = "workdir",
        path: str = "",
        max_chars: int = Query(default=120000, ge=1000, le=1_000_000),
        package_id: str | None = None,
        resource_mode: str | None = None,
        factory_session_id: str | None = None,
        package_session_id: str | None = None,
        create_agent_session_id: str | None = None,
        collaboration_id: str | None = None,
    ):
        event = await resource_command(
            runtime_bridge,
            "workspace_manage",
            {
                "action": "read",
                "scope": scope,
                "path": path,
                "max_chars": max_chars,
                **workspace_context_payload(
                    package_id=package_id,
                    resource_mode=resource_mode,
                    factory_session_id=factory_session_id,
                    package_session_id=package_session_id,
                    create_agent_session_id=create_agent_session_id,
                    collaboration_id=collaboration_id,
                ),
            },
            {"workspace_file_read"},
        )
        return {"event": event}

    @router.get("/raw")
    async def workspace_raw_file(
        scope: str = "workdir",
        path: str = "",
        package_id: str | None = None,
        resource_mode: str | None = None,
        factory_session_id: str | None = None,
        package_session_id: str | None = None,
        create_agent_session_id: str | None = None,
        collaboration_id: str | None = None,
    ):
        service = FrontendWorkspaceService(
            agent_package_runtime=AgentPackageRuntimeManager(),
            session_manager=FactorySessionManager.from_env(),
        )
        try:
            target = service.resolve_file(
                workspace_context_payload(
                    package_id=package_id,
                    resource_mode=resource_mode,
                    factory_session_id=factory_session_id,
                    package_session_id=package_session_id,
                    create_agent_session_id=create_agent_session_id,
                    collaboration_id=collaboration_id,
                ),
                scope=scope,
                relative_path=path,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        media_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        filename = target.name
        quoted_filename = quote(filename)
        return FileResponse(
            target,
            media_type=media_type,
            filename=filename,
            headers={"Content-Disposition": f"inline; filename*=UTF-8''{quoted_filename}"},
        )

    return router


def workspace_context_payload(
    *,
    package_id: str | None,
    resource_mode: str | None,
    factory_session_id: str | None,
    package_session_id: str | None,
    create_agent_session_id: str | None,
    collaboration_id: str | None,
) -> dict[str, str]:
    return {
        **optional_package(package_id),
        **({"resource_mode": resource_mode} if resource_mode else {}),
        **({"factory_session_id": factory_session_id} if factory_session_id else {}),
        **({"package_session_id": package_session_id} if package_session_id else {}),
        **({"create_agent_session_id": create_agent_session_id} if create_agent_session_id else {}),
        **({"collaboration_id": collaboration_id} if collaboration_id else {}),
    }
