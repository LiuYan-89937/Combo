from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.runtime_protocol import RuntimeProtocolDescriptor
from web_frontend.backend.dynamic_runtime_api import (
    DynamicRuntimeApiConfig,
    RequestPrincipalResolver,
    create_dynamic_runtime_router,
)
from web_frontend.backend.event_loop_watchdog import EventLoopWatchdog
from web_frontend.backend.parent_process_watchdog import start_parent_process_watchdog
from web_frontend.backend.routes.files import create_file_router
from web_frontend.backend.routes.browser_views import create_browser_view_router
from web_frontend.backend.routes.model_pool import create_model_pool_router
from web_frontend.backend.runtime_backend import RuntimeBackend, RuntimeBackendConfig


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
load_agentfactory_dotenv()


class HeaderPrincipalResolver(RequestPrincipalResolver):
    """Require the authenticated loopback client to name its stable principal."""

    def resolve(self, request: Request) -> str:
        principal_id = str(request.headers.get("X-AgentFactory-Principal") or "").strip()
        if not principal_id:
            raise HTTPException(status_code=401, detail="runtime principal header is required")
        return principal_id


def create_app(config: RuntimeBackendConfig | None = None) -> FastAPI:
    backend = RuntimeBackend(config or RuntimeBackendConfig.local(), logger)
    watchdog = EventLoopWatchdog(logger)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        start_parent_process_watchdog()
        watchdog.start(asyncio.get_running_loop())
        backend.start()
        try:
            yield
        finally:
            await backend.stop()
            watchdog.stop()

    application = FastAPI(
        title="FastAgentFactory Dynamic Runtime Service",
        lifespan=lifespan,
    )
    application.state.runtime_backend = backend

    @application.get("/health")
    async def health() -> dict[str, object]:
        descriptor = RuntimeProtocolDescriptor(build_revision=backend.config.build_revision)
        return {
            "status": "ready",
            "protocol": descriptor.model_dump(mode="json"),
            "generation": backend.application.generation.generation,
        }
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Content-Type",
            "Last-Event-ID",
            "X-AgentFactory-Build",
            "X-AgentFactory-Generation",
            "X-AgentFactory-Principal",
            "X-AgentFactory-Protocol",
            "X-AgentFactory-Schema",
        ],
    )
    application.include_router(
        create_dynamic_runtime_router(
            application=backend.application,
            supervisor=backend.supervisor,
            broadcaster=backend.broadcaster,
            principal_resolver=HeaderPrincipalResolver(),
            config=DynamicRuntimeApiConfig(
                keepalive_seconds=15.0,
                replay_limit=256,
                managed_workspace_root=backend.config.workspace_root,
            ),
        )
    )
    application.include_router(create_model_pool_router(usage_store=backend.application.stores.model_usage))
    application.include_router(create_file_router())
    application.include_router(create_browser_view_router(logger, backend.browser_runtime))
    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
