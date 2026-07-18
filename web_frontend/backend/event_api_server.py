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
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.runtime_kernel.persistence import close_shared_sqlite_checkpointers
from agent_factory.collaboration_system import CollaborationService
from agent_factory.agent_group_system import AgentGroupService
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand
from agent_factory.factory_graph.session import (
    FactorySessionManager,
    record_has_any_source,
    without_mode_source,
)
from agent_factory.tooling.skillhub import ensure_global_skillhub_cli
from web_frontend.backend.routes.agent_packages import create_agent_package_router
from web_frontend.backend.routes.agent_group import create_agent_group_router
from web_frontend.backend.routes.collaboration import create_collaboration_router
from web_frontend.backend.routes.create_agent import create_create_agent_router
from web_frontend.backend.routes.extensions import create_extensions_router
from web_frontend.backend.routes.knowledge import create_knowledge_router
from web_frontend.backend.routes.memory import create_memory_router
from web_frontend.backend.routes.model_pool import create_model_pool_router
from web_frontend.backend.routes.runtime import create_runtime_router
from web_frontend.backend.routes.scheduler import create_scheduler_router
from web_frontend.backend.routes.tips import create_tip_router
from web_frontend.backend.routes.workspace import create_workspace_router
from web_frontend.backend.runtime_bridge import RuntimeBridge
from web_frontend.backend.event_loop_watchdog import EventLoopWatchdog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_agentfactory_dotenv()

app = FastAPI(title="FastAgentFactory Web Runtime Service")
runtime_bridge = RuntimeBridge()
event_loop_watchdog = EventLoopWatchdog(logger)
collaboration_service = CollaborationService(
    runtime_factory=lambda: _agent_package_runtime(runtime_bridge),
    factory_session_deleter=lambda session_id, owned_chat_session_ids: _delete_collaboration_factory_session(
        runtime_bridge,
        session_id,
        owned_chat_session_ids,
    ),
    logger=logger,
)
agent_group_service = AgentGroupService(
    logger=logger,
    runtime_factory=lambda: _agent_package_runtime(runtime_bridge),
)


def _delete_collaboration_factory_session(
    bridge: RuntimeBridge,
    session_id: str,
    owned_chat_session_ids: list[str],
) -> dict[str, object]:
    clean_session_id = str(session_id or "").strip()
    if not clean_session_id:
        return {"session_id": "", "deleted": False, "missing": True}
    manager = FactorySessionManager.from_env()
    try:
        record = manager.load(clean_session_id)
    except FileNotFoundError:
        return {"session_id": clean_session_id, "deleted": False, "missing": True}
    linked_session_id = str(record.chat_agent_package_session_id or "").strip()
    owned = {str(item or "").strip() for item in owned_chat_session_ids if str(item or "").strip()}
    if linked_session_id and linked_session_id not in owned:
        raise ValueError(
            "factory session chat ownership does not match the collaboration main Agent session"
        )
    adapter = bridge.adapter
    retained = record_has_any_source(without_mode_source(record, "chat"))
    if adapter is None:
        updated = without_mode_source(record, "chat")
        if retained:
            manager.save(updated)
        else:
            manager.delete(clean_session_id)
        return {
            "session_id": record.session_id,
            "deleted": not retained,
            "detached_chat": True,
        }
    adapter.delete_session(
        FactoryFrontendCommand(
            type="delete_session",
            request_id=f"collaboration-delete-{uuid4().hex}",
            session_id=clean_session_id,
            mode="chat",
        )
    )
    return {
        "session_id": clean_session_id,
        "deleted": not retained,
        "detached_chat": True,
    }


def _observe_agent_group_runtime_event(event_payload: dict) -> None:
    """Persist group runtime events, then dispatch the next member turn when a lane frees."""
    agent_group_service.observe_runtime_event(event_payload)
    payload = event_payload.get("payload") if isinstance(event_payload.get("payload"), dict) else {}
    group_id = str(payload.get("group_id") or "").strip()
    if not group_id or event_payload.get("event_type") not in {"run_completed", "run_failed", "run_cancelled"}:
        return
    runtime_bridge.schedule_coroutine(_dispatch_queued_agent_group_runs(group_id))


async def _dispatch_queued_agent_group_runs(group_id: str) -> None:
    try:
        runtime = _agent_package_runtime(runtime_bridge)
        commands = agent_group_service.prepare_queued_run_commands(group_id, runtime)
        for command in commands:
            await runtime_bridge.send_frontend_command(command)
    except Exception:
        logger.exception("Failed to dispatch queued agent-group runs for %s", group_id)

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
app.include_router(create_agent_group_router(runtime_bridge, agent_group_service))
app.include_router(create_create_agent_router())
app.include_router(create_workspace_router(runtime_bridge))
app.include_router(create_knowledge_router(runtime_bridge))
app.include_router(create_memory_router(runtime_bridge))
app.include_router(create_extensions_router(runtime_bridge))
app.include_router(create_scheduler_router(runtime_bridge))
app.include_router(create_model_pool_router())
app.include_router(create_tip_router())


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
    event_loop_watchdog.start(asyncio.get_running_loop())
    await _ensure_skillhub_cli()
    await runtime_bridge.start()
    recovered_group_commits = agent_group_service.recover_workspace_transactions()
    if recovered_group_commits:
        logger.info("Recovered %s pending agent-group workspace commits", len(recovered_group_commits))
    runtime_bridge.add_event_observer(_observe_agent_group_runtime_event)
    collaboration_service.start()


@app.on_event("shutdown")
async def shutdown_event():
    collaboration_service.stop()
    agent_group_service.shutdown()
    runtime_bridge.remove_event_observer(_observe_agent_group_runtime_event)
    await runtime_bridge.stop()
    close_shared_sqlite_checkpointers()
    event_loop_watchdog.stop()


def _agent_package_runtime(runtime_bridge: RuntimeBridge) -> AgentPackageRuntimeManager:
    adapter = runtime_bridge.adapter
    runtime = getattr(adapter, "agent_package_runtime", None) if adapter is not None else None
    return runtime if isinstance(runtime, AgentPackageRuntimeManager) else AgentPackageRuntimeManager()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
