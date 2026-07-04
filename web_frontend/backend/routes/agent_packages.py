from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from web_frontend.backend.runtime_bridge import RuntimeBridge
from web_frontend.backend.routes.utils import send_and_wait

logger = logging.getLogger(__name__)


def create_agent_package_router(runtime_bridge: RuntimeBridge, logger: logging.Logger) -> APIRouter:
    router = APIRouter(prefix="/api/agent-packages")

    @router.get("")
    async def list_agent_packages():
        event = await send_and_wait(runtime_bridge, "list_agent_packages", {}, {"agent_packages_listed"})
        return {"event": event}

    @router.post("/select")
    async def select_agent_package(payload: dict[str, Any]):
        event = await send_and_wait(runtime_bridge, "select_agent_package", payload, {"agent_package_selected"})
        return {"event": event}

    @router.get("/instances")
    async def list_agent_package_instances():
        event = await send_and_wait(
            runtime_bridge,
            "list_agent_package_instances",
            {},
            {"agent_package_instances_listed"},
        )
        return {"event": event}

    @router.get("/recent-sessions")
    async def list_recent_agent_package_sessions(limit: int = Query(default=5, ge=1, le=20)):
        runtime = AgentPackageRuntimeManager()
        sessions: list[dict[str, Any]] = []
        for package in runtime.list_packages():
            package_id = str(package.get("package_id") or "").strip()
            if not package_id:
                continue
            package_name = str(package.get("agent_name") or package.get("name") or package_id)
            try:
                package_sessions = runtime.list_sessions(package_id)
            except Exception as exc:
                logger.warning("Failed to list sessions for package %s: %s", package_id, exc)
                continue
            for session in package_sessions:
                item = dict(session)
                item["package_id"] = package_id
                item["package_name"] = package_name
                item["agent_name"] = package_name
                sessions.append(item)
        sessions.sort(key=session_updated_sort_key, reverse=True)
        return {"sessions": sessions[:limit]}

    @router.post("/{package_id}/initialize")
    async def initialize_agent_package(package_id: str):
        event = await send_and_wait(
            runtime_bridge,
            "initialize_agent_package",
            {"package_id": package_id},
            {"agent_package_instance_updated"},
            timeout_seconds=180.0,
            event_filter=lambda item: _is_initialize_terminal_event(item, package_id=package_id),
        )
        return {"event": event}

    @router.post("/{package_id}/shutdown")
    async def shutdown_agent_package_instance(package_id: str):
        event = await send_and_wait(
            runtime_bridge,
            "shutdown_agent_package_instance",
            {"package_id": package_id},
            {"agent_package_instance_updated"},
        )
        return {"event": event}

    @router.delete("/{package_id}")
    async def delete_agent_package(package_id: str):
        event = await send_and_wait(
            runtime_bridge,
            "delete_agent_package",
            {"package_id": package_id},
            {"agent_package_deleted"},
        )
        return {"event": event}

    @router.get("/{package_id}/export")
    async def export_agent_package(package_id: str):
        try:
            archive_path = AgentPackageRuntimeManager().export_package_archive(package_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        filename = f"{package_id}.zip"
        quoted_filename = quote(filename)
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename=filename,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"},
            background=BackgroundTask(unlink_file, archive_path),
        )

    @router.get("/{package_id}/sessions")
    async def list_agent_package_sessions(package_id: str):
        event = await send_and_wait(
            runtime_bridge,
            "list_agent_package_sessions",
            {"package_id": package_id},
            {"agent_package_sessions_listed"},
        )
        return {"event": event}

    @router.get("/{package_id}/sessions/{session_id}")
    async def load_agent_package_session(package_id: str, session_id: str):
        event = await send_and_wait(
            runtime_bridge,
            "load_agent_package_session",
            {"package_id": package_id, "session_id": session_id},
            {"agent_package_session_loaded"},
        )
        return {"event": event}

    @router.delete("/{package_id}/sessions/{session_id}")
    async def delete_agent_package_session(package_id: str, session_id: str):
        event = await send_and_wait(
            runtime_bridge,
            "delete_agent_package_session",
            {"package_id": package_id, "session_id": session_id},
            {"agent_package_session_deleted"},
        )
        return {"event": event}

    return router


def session_updated_sort_key(session: dict[str, Any]) -> str:
    return str(session.get("updated_at") or session.get("created_at") or "")


def _is_initialize_terminal_event(item: dict[str, Any], *, package_id: str) -> bool:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    if str(payload.get("package_id") or "").strip() != package_id:
        return False
    status = str(payload.get("status") or "").strip()
    return payload.get("ready") is True or status == "failed"


def unlink_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Failed to remove temporary file: %s", path)
