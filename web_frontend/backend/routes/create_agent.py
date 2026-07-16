from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.resource_system import ResourceStore
from agent_factory.runtime_contracts import AgentPackageLoader, ResourcesContract


def create_create_agent_router() -> APIRouter:
    router = APIRouter(prefix="/api/create-agent")

    @router.put("/sessions/{session_id}/resources/{resource_id}")
    async def put_create_agent_resource(session_id: str, resource_id: str, payload: dict[str, Any]):
        if "value" not in payload:
            raise HTTPException(status_code=400, detail="resource value is required")
        workspace = CreateAgentWorkspace.for_session(session_id)
        try:
            package = AgentPackageLoader().load_path(workspace.package_manifest_path())
            contract = ResourcesContract.model_validate(package.contracts.get("resources") or {})
            descriptors = {item.resource_id: item for item in contract.config.resource_descriptors}
            descriptor = descriptors.get(resource_id)
            if descriptor is None:
                raise ValueError(f"resource is not declared by the manufacturing package: {resource_id}")
            result = ResourceStore().put(workspace.root.name, descriptor, payload["value"])
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return result

    return router
