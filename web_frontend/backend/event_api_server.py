from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import json
import logging
from threading import Lock
from time import monotonic
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.types import Receive, Scope, Send

from web_frontend.backend.event_loop_watchdog import EventLoopWatchdog
from web_frontend.backend.frontend_origins import allowed_frontend_origins

if TYPE_CHECKING:
    from web_frontend.backend.runtime_backend import RuntimeBackend, RuntimeBackendConfig


logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("httpcore2").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


class RuntimeStartupState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._started_at = monotonic()
        self._status = "starting"
        self._phase = "loading_runtime"
        self._error: str | None = None
        self._protocol: dict[str, object] | None = None
        self._runtime_application: FastAPI | None = None
        self._backend: RuntimeBackend | None = None
        self._stopping = False

    def set_phase(self, phase: str) -> None:
        with self._lock:
            if self._status == "starting":
                self._phase = str(phase or "initializing")

    def ready(
        self,
        *,
        backend: RuntimeBackend,
        application: FastAPI,
        protocol: dict[str, object],
    ) -> None:
        with self._lock:
            self._backend = backend
            self._runtime_application = application
            self._protocol = protocol
            self._phase = "ready"
            self._status = "ready"

    def attach_backend(self, backend: RuntimeBackend) -> None:
        with self._lock:
            self._backend = backend

    def failed(self, error: BaseException) -> None:
        with self._lock:
            self._error = f"{type(error).__name__}: {error}"
            self._phase = "failed"
            self._status = "failed"

    def begin_stopping(self) -> RuntimeBackend | None:
        with self._lock:
            self._stopping = True
            self._phase = "stopping"
            return self._backend

    @property
    def stopping(self) -> bool:
        with self._lock:
            return self._stopping

    @property
    def runtime_application(self) -> FastAPI | None:
        with self._lock:
            return self._runtime_application

    def health(self) -> tuple[int, dict[str, object]]:
        with self._lock:
            payload: dict[str, object] = {
                "status": self._status,
                "phase": self._phase,
                "elapsed_ms": round((monotonic() - self._started_at) * 1000),
            }
            if self._protocol is not None:
                payload["protocol"] = self._protocol
            if self._error is not None:
                payload["error"] = self._error
            status_code = 200 if self._status == "ready" else 500 if self._status == "failed" else 503
            return status_code, payload


class DeferredRuntimeApplication:
    """Expose startup health immediately and delegate to the full runtime once ready."""

    def __init__(self, bootstrap: FastAPI, state: RuntimeStartupState) -> None:
        self.bootstrap = bootstrap
        self.state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan" or (
            scope["type"] == "http" and scope.get("path") == "/health"
        ):
            await self.bootstrap(scope, receive, send)
            return
        runtime_application = self.state.runtime_application
        if runtime_application is None:
            status_code, payload = self.state.health()
            await JSONResponse(payload, status_code=status_code)(scope, receive, send)
            return
        await runtime_application(scope, receive, send)


def create_app(config: RuntimeBackendConfig | None = None) -> DeferredRuntimeApplication:
    state = RuntimeStartupState()
    watchdog = EventLoopWatchdog(logger)
    initialization: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal initialization
        loop = asyncio.get_running_loop()
        watchdog.start(loop)
        initialization = asyncio.create_task(
            _initialize_runtime(state=state, config=config, loop=loop),
            name="combo-runtime-initialization",
        )
        try:
            yield
        finally:
            backend = state.begin_stopping()
            if initialization is not None and not initialization.done():
                initialization.cancel()
            if backend is not None:
                try:
                    await backend.stop()
                finally:
                    backend.frontend_events.stop()
            watchdog.stop()

    bootstrap = FastAPI(title="Combo Bootstrap Service", lifespan=lifespan)
    _configure_cors(bootstrap, allowed_frontend_origins())

    @bootstrap.get("/health")
    async def health() -> JSONResponse:
        status_code, payload = state.health()
        return JSONResponse(payload, status_code=status_code)

    return DeferredRuntimeApplication(bootstrap, state)


async def _initialize_runtime(
    *,
    state: RuntimeStartupState,
    config: RuntimeBackendConfig | None,
    loop: asyncio.AbstractEventLoop,
) -> None:
    backend: RuntimeBackend | None = None
    try:
        state.set_phase("loading_runtime_modules")
        from combo.runtime_protocol import RuntimeProtocolDescriptor
        from web_frontend.backend.runtime_backend import RuntimeBackend, RuntimeBackendConfig

        runtime_config = config or RuntimeBackendConfig.local()
        state.set_phase("constructing_runtime")
        backend = await asyncio.to_thread(
            RuntimeBackend,
            runtime_config,
            logger,
            state.set_phase,
        )
        state.attach_backend(backend)
        if state.stopping:
            return
        state.set_phase("starting_runtime_services")
        backend.frontend_events.start(loop)
        backend.start()
        runtime_application = _build_runtime_application(backend)
        descriptor = RuntimeProtocolDescriptor(build_revision=backend.config.build_revision)
        state.ready(
            backend=backend,
            application=runtime_application,
            protocol=descriptor.model_dump(mode="json"),
        )
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        logger.exception("Combo runtime initialization failed")
        state.failed(exc)
        if backend is not None and not state.stopping:
            try:
                await backend.stop()
            finally:
                backend.frontend_events.stop()


def _build_runtime_application(backend: RuntimeBackend) -> FastAPI:
    from web_frontend.backend.dynamic_runtime_api import (
        DynamicRuntimeApiConfig,
        RequestPrincipalResolver,
        create_dynamic_runtime_router,
    )
    from web_frontend.backend.frontend_interaction_api import create_frontend_interaction_router
    from web_frontend.backend.routes.attachments import create_attachment_router
    from web_frontend.backend.routes.browser_views import create_browser_view_router
    from web_frontend.backend.routes.files import create_file_router
    from web_frontend.backend.routes.model_pool import create_model_pool_router

    class HeaderPrincipalResolver(RequestPrincipalResolver):
        def resolve(self, request: Request) -> str:
            principal_id = str(request.headers.get("X-Combo-Principal") or "").strip()
            if not principal_id:
                raise HTTPException(status_code=401, detail="runtime principal header is required")
            return principal_id

    application = FastAPI(title="Combo Dynamic Runtime Service")
    application.state.runtime_backend = backend

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

    _configure_cors(application, backend.config.allowed_frontend_origins)
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


def _configure_cors(application: FastAPI, origins: tuple[str, ...]) -> None:
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
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


app = create_app()


def _frontend_sse(event: dict[str, object]) -> str:
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event['event_id']}\nevent: combo_frontend_event\ndata: {payload}\n\n"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
