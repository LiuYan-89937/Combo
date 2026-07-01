from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from web_frontend.backend.runtime_bridge import RuntimeBridge
from web_frontend.backend.routes.utils import optional_package, resource_command


def create_extensions_router(runtime_bridge: RuntimeBridge) -> APIRouter:
    router = APIRouter(prefix="/api/extensions")

    @router.get("")
    async def list_extensions(package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {"action": "list", **optional_package(package_id)},
            {"extension_configs_listed"},
        )
        return {"event": event}

    @router.post("/mcp")
    async def save_mcp(payload: dict[str, Any]):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {"action": "upsert_mcp", **payload},
            {"extension_config_updated"},
        )
        return {"event": event}

    @router.post("/mcp/test")
    async def test_mcp(payload: dict[str, Any]):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {"action": "test_mcp", **payload},
            {"extension_config_tested"},
            timeout_seconds=60.0,
        )
        return {"event": event}

    @router.patch("/mcp/{server_id}")
    async def set_mcp_enabled(server_id: str, payload: dict[str, Any]):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "set_mcp_enabled",
                "server_id": server_id,
                "enabled": payload.get("enabled", True),
                **optional_package(payload.get("package_id")),
            },
            {"extension_config_updated"},
        )
        return {"event": event}

    @router.delete("/mcp/{server_id}")
    async def remove_mcp(server_id: str, package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {"action": "remove_mcp", "server_id": server_id, **optional_package(package_id)},
            {"extension_config_updated"},
        )
        return {"event": event}

    @router.post("/skills")
    async def save_skill(payload: dict[str, Any]):
        package_id = payload.get("package_id")
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "upsert_skill",
                "skill": payload.get("skill") if isinstance(payload.get("skill"), dict) else payload,
                "replace_skill_id": payload.get("replace_skill_id"),
                **optional_package(package_id),
            },
            {"extension_config_updated"},
        )
        return {"event": event}

    @router.patch("/skills/{skill_id}")
    async def set_skill_enabled(skill_id: str, payload: dict[str, Any]):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {
                "action": "set_skill_enabled",
                "skill_id": skill_id,
                "enabled": payload.get("enabled", True),
                **optional_package(payload.get("package_id")),
            },
            {"extension_config_updated"},
        )
        return {"event": event}

    @router.delete("/skills/{skill_id}")
    async def remove_skill(skill_id: str, package_id: str | None = None):
        event = await resource_command(
            runtime_bridge,
            "extensions_manage",
            {"action": "remove_skill", "skill_id": skill_id, **optional_package(package_id)},
            {"extension_config_updated"},
        )
        return {"event": event}

    return router
