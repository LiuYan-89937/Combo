from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import json

from combo.runtime_protocol import RuntimeProtocolDescriptor
from web_frontend.backend.dynamic_runtime_api import (
    DynamicRuntimeApiConfig,
    RequestPrincipalResolver,
    create_dynamic_runtime_router,
)
from web_frontend.backend.event_loop_watchdog import EventLoopWatchdog
from web_frontend.backend.routes.files import create_file_router
from web_frontend.backend.routes.browser_views import create_browser_view_router
from web_frontend.backend.routes.model_pool import create_model_pool_router
from web_frontend.backend.frontend_interaction_api import create_frontend_interaction_router
from web_frontend.backend.runtime_backend import RuntimeBackend, RuntimeBackendConfig
from web_frontend.backend.routes.attachments import create_attachment_router


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HeaderPrincipalResolver(RequestPrincipalResolver):
    """Require the authenticated loopback client to name its stable principal."""

    def resolve(self, request: Request) -> str:
        principal_id = str(request.headers.get("X-Combo-Principal") or "").strip()
        if not principal_id:
            raise HTTPException(status_code=401, detail="runtime principal header is required")
        return principal_id


def create_app(config: RuntimeBackendConfig | None = None) -> FastAPI:
    backend = RuntimeBackend(config or RuntimeBackendConfig.local(), logger)
    watchdog = EventLoopWatchdog(logger)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        watchdog.start(asyncio.get_running_loop())
        backend.frontend_events.start(asyncio.get_running_loop())
        try:
            backend.start()
            yield
        finally:
            try:
                await backend.stop()
            finally:
                backend.frontend_events.stop()
                watchdog.stop()

    application = FastAPI(
        title="Combo Dynamic Runtime Service",
        lifespan=lifespan,
    )
    application.state.runtime_backend = backend

    @application.get("/health")
    async def health() -> dict[str, object]:
        descriptor = RuntimeProtocolDescriptor(build_revision=backend.config.build_revision)
        return {
            "status": "ready",
            "protocol": descriptor.model_dump(mode="json"),
        }

    @application.get("/events")
    async def frontend_events(request: Request, principal_id: str) -> StreamingResponse:
        subscription = await backend.frontend_events.subscribe(principal_id)

        async def stream():
            try:
                ready = backend.frontend_events.ready_event(principal_id)
                yield _frontend_sse(ready)
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(subscription.queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield "event: combo_frontend_heartbeat\ndata: {}\n\n"
                        continue
                    yield _frontend_sse(event)
            finally:
                await backend.frontend_events.unsubscribe(subscription)

        return StreamingResponse(stream(), media_type="text/event-stream")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(backend.config.allowed_frontend_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Content-Type",
            "Last-Event-ID",
            "X-Combo-Build",
            "X-Combo-Client",
            "X-Combo-Principal",
            "X-Combo-Protocol",
            "X-Combo-Schema",
            "X-Combo-Timezone",
        ],
    )
    application.include_router(
        create_dynamic_runtime_router(
            application=backend.application,
            supervisor=backend.supervisor,
            broadcaster=backend.broadcaster,
            principal_resolver=HeaderPrincipalResolver(),
            capability_pools=backend,
            config=DynamicRuntimeApiConfig(
                keepalive_seconds=15.0,
                replay_limit=256,
                managed_workspace_root=backend.config.workspace_root,
                maximum_skill_file_bytes=backend.config.maximum_skill_file_bytes,
                maximum_skill_bytes=backend.config.maximum_skill_bytes,
                maximum_tool_file_bytes=backend.config.maximum_tool_file_bytes,
                maximum_tool_bytes=backend.config.maximum_tool_bytes,
            ),
        )
    )
    application.include_router(create_model_pool_router(
        usage_store=backend.application.stores.model_usage,
        on_embedding_configuration_changed=backend.refresh_capability_search_embeddings,
        on_image_generation_configuration_changed=backend.refresh_model_bound_capabilities,
    ))
    application.include_router(create_frontend_interaction_router(backend))
    application.include_router(create_attachment_router())
    application.include_router(create_file_router())
    application.include_router(create_browser_view_router(logger, backend.browser_runtime))
    return application


app = create_app()


def _frontend_sse(event: dict[str, object]) -> str:
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event['event_id']}\nevent: combo_frontend_event\ndata: {payload}\n\n"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
