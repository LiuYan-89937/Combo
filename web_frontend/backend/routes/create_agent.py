from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from agent_factory.create_agent.publish_tool import confirm_and_publish
from agent_factory.create_agent.workspace import CreateAgentWorkspace


def create_create_agent_router() -> APIRouter:
    router = APIRouter(prefix="/api/create-agent")

    @router.post("/sessions/{session_id}/publish")
    async def publish_create_agent_workspace(session_id: str, payload: dict[str, Any] | None = None):
        confirmation = _confirmation_text(payload)
        try:
            result = confirm_and_publish(
                workspace=CreateAgentWorkspace.for_session(session_id),
                confirmation=confirmation,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"published": result}

    return router


def _confirmation_text(payload: dict[str, Any] | None) -> str:
    if isinstance(payload, dict):
        text = str(payload.get("confirmation") or "").strip()
        if text:
            return text
    return "用户在 Web 界面点击发布"
