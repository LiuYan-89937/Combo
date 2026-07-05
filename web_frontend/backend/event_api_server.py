"""
FastAPI Event/API Server - FastAgentFactory Web Runtime Service.

The module only assembles the app. Runtime lifecycle management and route groups
live in dedicated modules so frontend-facing concerns do not share one file.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.collaboration_system import CollaborationService
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.tooling.skillhub import ensure_global_skillhub_cli
from web_frontend.backend.routes.agent_packages import create_agent_package_router
from web_frontend.backend.routes.collaboration import create_collaboration_router
from web_frontend.backend.routes.create_agent import create_create_agent_router
from web_frontend.backend.routes.extensions import create_extensions_router
from web_frontend.backend.routes.knowledge import create_knowledge_router
from web_frontend.backend.routes.memory import create_memory_router
from web_frontend.backend.routes.model_pool import create_model_pool_router
from web_frontend.backend.routes.runtime import create_runtime_router
from web_frontend.backend.routes.scheduler import create_scheduler_router
from web_frontend.backend.routes.workspace import create_workspace_router
from web_frontend.backend.runtime_bridge import RuntimeBridge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_agentfactory_dotenv()

app = FastAPI(title="FastAgentFactory Web Runtime Service")
runtime_bridge = RuntimeBridge()
collaboration_service = CollaborationService(
    runtime_factory=lambda: _agent_package_runtime(runtime_bridge),
    logger=logger,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(create_runtime_router(runtime_bridge, logger))
app.include_router(create_agent_package_router(runtime_bridge, logger))
app.include_router(create_collaboration_router(runtime_bridge, collaboration_service))
app.include_router(create_create_agent_router())
app.include_router(create_workspace_router(runtime_bridge))
app.include_router(create_knowledge_router(runtime_bridge))
app.include_router(create_memory_router(runtime_bridge))
app.include_router(create_extensions_router(runtime_bridge))
app.include_router(create_scheduler_router(runtime_bridge))
app.include_router(create_model_pool_router())


async def _ensure_skillhub_cli() -> None:
    try:
        result = await asyncio.to_thread(ensure_global_skillhub_cli, auto_install=True)
    except Exception as exc:
        logger.warning("SkillHUB CLI initialization failed: %s: %s", type(exc).__name__, exc)
        return
    if result.get("cli_available"):
        logger.info(
            "SkillHUB CLI ready: %s %s",
            result.get("cli_path") or "skillhub",
            result.get("cli_version") or "",
        )
        return
    logger.warning("SkillHUB CLI is not available; set AGENTFACTORY_SKILLHUB_AUTO_INSTALL=true or install it manually.")


@app.on_event("startup")
async def startup_event():
    await _ensure_skillhub_cli()
    await runtime_bridge.start()
    collaboration_service.start()


@app.on_event("shutdown")
async def shutdown_event():
    collaboration_service.stop()
    await runtime_bridge.stop()


def _agent_package_runtime(runtime_bridge: RuntimeBridge) -> AgentPackageRuntimeManager:
    adapter = runtime_bridge.adapter
    runtime = getattr(adapter, "agent_package_runtime", None) if adapter is not None else None
    return runtime if isinstance(runtime, AgentPackageRuntimeManager) else AgentPackageRuntimeManager()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
