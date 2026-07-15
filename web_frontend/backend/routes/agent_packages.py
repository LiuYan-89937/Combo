from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import SYSTEM_CHAT_PACKAGE_ID
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
            if not package_id or package_id == SYSTEM_CHAT_PACKAGE_ID:
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

    @router.patch("/{package_id}/context-config")
    async def update_agent_package_context_config(package_id: str, payload: dict[str, Any]):
        try:
            summary = AgentPackageRuntimeManager().update_context_config(
                package_id,
                _validated_context_config_payload(payload),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"package": summary}

    @router.get("/{package_id}/resources")
    async def get_agent_package_resources(package_id: str):
        try:
            return AgentPackageRuntimeManager().resource_status(package_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("/{package_id}/resources/{resource_id}")
    async def put_agent_package_resource(package_id: str, resource_id: str, payload: dict[str, Any]):
        if "value" not in payload:
            raise HTTPException(status_code=400, detail="resource value is required")
        try:
            return AgentPackageRuntimeManager().put_resource(package_id, resource_id, payload["value"])
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.delete("/{package_id}/resources/{resource_id}")
    async def delete_agent_package_resource(package_id: str, resource_id: str):
        try:
            return AgentPackageRuntimeManager().delete_resource(package_id, resource_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

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


def _validated_context_config_payload(payload: dict[str, Any]) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for key in ("context_window_tokens", "compression_threshold_tokens"):
        if key not in payload:
            continue
        value = payload.get(key)
        if value is None:
            result[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be an integer or null")
        minimum = 1000
        if value < minimum:
            raise ValueError(f"{key} must be greater than or equal to {minimum}")
        result[key] = value
    return result


def unlink_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Failed to remove temporary file: %s", path)
