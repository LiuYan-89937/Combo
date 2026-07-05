from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException

from agent_factory.collaboration_system import CollaborationService
from agent_factory.collaboration_system.store import CollaborationStoreError, SYSTEM_CHAT_PACKAGE_ID
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from web_frontend.backend.runtime_bridge import RuntimeBridge


def create_collaboration_router(runtime_bridge: RuntimeBridge, service: CollaborationService) -> APIRouter:
    router = APIRouter(prefix="/api/collaboration")

    @router.get("/agents")
    async def list_collaboration_agents():
        return {"agents": _collaboration_agents(runtime_bridge)}

    @router.get("/sessions")
    async def list_sessions():
        return {"sessions": service.store.list_sessions()}

    @router.post("/sessions")
    async def create_session(payload: dict[str, Any]):
        try:
            session = service.store.create_session(
                title=str(payload.get("title") or ""),
                main_agent_package_id=payload.get("main_agent_package_id"),
                approval_mode=str(payload.get("approval_mode") or ""),
            )
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"session": session}

    @router.get("/sessions/{collaboration_id}")
    async def get_session(collaboration_id: str):
        try:
            return {"session": service.store.get_session(collaboration_id)}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.patch("/sessions/{collaboration_id}")
    async def update_session(collaboration_id: str, payload: dict[str, Any]):
        try:
            return {"session": service.store.update_session(collaboration_id, payload)}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/sessions/{collaboration_id}/complete")
    async def complete_session(collaboration_id: str, payload: dict[str, Any]):
        try:
            return {"session": service.complete_session(collaboration_id, {**payload, "speaker_type": "user"})}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.delete("/sessions/{collaboration_id}")
    async def delete_session(collaboration_id: str):
        try:
            return service.delete_session(collaboration_id)
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/sessions/{collaboration_id}/messages")
    async def add_message(collaboration_id: str, payload: dict[str, Any]):
        try:
            return {"session": service.store.add_message(collaboration_id, payload)}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/sessions/{collaboration_id}/main-agent-prompt")
    async def main_agent_prompt(collaboration_id: str, payload: dict[str, Any]):
        try:
            prompt = service.build_main_agent_prompt(
                collaboration_id=collaboration_id,
                user_message=str(payload.get("message") or ""),
                worker_agents=[
                    agent for agent in _collaboration_agents(runtime_bridge)
                    if bool(agent.get("available_as_worker"))
                ],
            )
            return {"prompt": prompt}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/sessions/{collaboration_id}/tasks")
    async def create_task(collaboration_id: str, payload: dict[str, Any]):
        try:
            return {"session": service.create_task(collaboration_id, payload)}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/sessions/{collaboration_id}/dispatch-ready")
    async def dispatch_ready_tasks(collaboration_id: str, payload: dict[str, Any] | None = None):
        try:
            limit = payload.get("limit") if isinstance(payload, dict) else None
            return service.dispatch_ready(
                collaboration_id,
                limit=int(limit) if limit is not None else None,
            )
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/sessions/{collaboration_id}/tasks/{task_id}/start")
    async def start_task(collaboration_id: str, task_id: str):
        try:
            response = service.start_task(collaboration_id, task_id)
            result = response.get("result")
            return {
                "result": asdict(result) if result is not None else None,
                "session": response["session"],
                "message": response.get("message"),
            }
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/sessions/{collaboration_id}/tasks/{task_id}/cancel")
    async def cancel_task(collaboration_id: str, task_id: str, payload: dict[str, Any] | None = None):
        try:
            return {"session": service.cancel_task(collaboration_id, task_id, payload or {})}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/sessions/{collaboration_id}/tasks/{task_id}/approval")
    async def resolve_task_approval(collaboration_id: str, task_id: str, payload: dict[str, Any]):
        try:
            response = service.resolve_task_approval(collaboration_id, task_id, payload)
            result = response.get("result")
            return {
                "result": asdict(result) if result is not None else None,
                "session": response["session"],
                "message": response.get("message"),
            }
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.patch("/sessions/{collaboration_id}/tasks/{task_id}")
    async def update_task(collaboration_id: str, task_id: str, payload: dict[str, Any]):
        try:
            return {"session": service.update_task(collaboration_id, task_id, payload)}
        except Exception as exc:
            raise _http_error(exc) from exc

    return router


def _agent_package_runtime(runtime_bridge: RuntimeBridge) -> AgentPackageRuntimeManager:
    adapter = runtime_bridge.adapter
    runtime = getattr(adapter, "agent_package_runtime", None) if adapter is not None else None
    return runtime if isinstance(runtime, AgentPackageRuntimeManager) else AgentPackageRuntimeManager()


def _collaboration_agents(runtime_bridge: RuntimeBridge) -> list[dict[str, Any]]:
    runtime = _agent_package_runtime(runtime_bridge)
    packages = runtime.list_packages()
    agents: list[dict[str, Any]] = [
        {
            "package_id": SYSTEM_CHAT_PACKAGE_ID,
            "agent_name": "闲聊主 Agent",
            "agent_description": "使用系统闲聊作为协作主 Agent。",
            "source": "system",
            "available_as_main": True,
            "available_as_worker": False,
        }
    ]
    for package in packages:
        package_id = str(package.get("package_id") or "").strip()
        if not package_id or package_id == SYSTEM_CHAT_PACKAGE_ID:
            continue
        agents.append(
            {
                "package_id": package_id,
                "agent_name": package.get("agent_name") or package.get("name") or package_id,
                "agent_description": package.get("agent_description") or "",
                "source": "package",
                "available_as_main": True,
                "available_as_worker": True,
                "status": package.get("status"),
            }
        )
    return agents


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CollaborationStoreError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
