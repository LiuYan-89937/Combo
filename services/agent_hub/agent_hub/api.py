from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent_hub.app_releases import AppReleaseRegistry
from agent_hub.auth import (
    OAUTH_STATE_COOKIE,
    SESSION_COOKIE,
    AuthenticationError,
    AuthorizationPending,
    AuthService,
    public_user_view,
)
from agent_hub.config import ConfigurationError, Settings, get_settings
from agent_hub.database import Database
from agent_hub.oss_store import ObjectStore
from agent_hub.registry import AgentHubRegistry, RegistryError


LOGGER = logging.getLogger("agent_hub.api")


class UploadCreateRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(gt=0)


class ReviewRequest(BaseModel):
    message: str = Field(default="", max_length=2_000)


class DevicePollRequest(BaseModel):
    device_code: str = Field(min_length=1, max_length=500)


class DesktopAuthRequest(BaseModel):
    flow_id: str = Field(min_length=1, max_length=100)
    poll_secret: str = Field(min_length=20, max_length=500)


class AppReleaseCreateRequest(BaseModel):
    version: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    notes_markdown: str = Field(min_length=1, max_length=100_000)


class AppReleaseUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes_markdown: str = Field(min_length=1, max_length=100_000)


class AppReleaseAssetCreateRequest(BaseModel):
    asset_kind: str = Field(default="installer", min_length=1, max_length=20)
    platform: str = Field(min_length=1, max_length=20)
    architecture: str = Field(min_length=1, max_length=20)
    filename: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(gt=0)
    updater_signature: str = Field(default="", max_length=20_000)


class ApplicationServices:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = Database(settings)
        self.auth = AuthService(settings, self.database)
        self.object_store = ObjectStore(settings)
        self.registry = AgentHubRegistry(settings, self.database, self.object_store)
        self.app_releases = AppReleaseRegistry(
            settings,
            self.database,
            self.object_store,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    services = ApplicationServices(get_settings())
    services.database.initialize()
    app.state.services = services
    yield


app = FastAPI(
    title="FastAgentHub API",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

_configured_origins = get_settings().cors_origins
if _configured_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(_configured_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid4().hex
    try:
        response = await call_next(request)
    except Exception:
        LOGGER.exception(
            "unhandled request failure",
            extra={"request_id": request_id, "path": request.url.path},
        )
        response = JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "internal server error",
                    "request_id": request_id,
                }
            },
        )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.exception_handler(AuthenticationError)
async def authentication_error(_: Request, exc: AuthenticationError) -> JSONResponse:
    forbidden = "administrator" in str(exc).casefold()
    return _error_response(403 if forbidden else 401, "authentication_error", str(exc))


@app.exception_handler(AuthorizationPending)
async def authorization_pending(_: Request, exc: AuthorizationPending) -> JSONResponse:
    return JSONResponse(
        status_code=202,
        headers={"Retry-After": str(exc.retry_after_seconds)},
        content={
            "status": exc.code,
            "message": str(exc),
            "retry_after_seconds": exc.retry_after_seconds,
        },
    )


@app.exception_handler(RegistryError)
async def registry_error(_: Request, exc: RegistryError) -> JSONResponse:
    if exc.code.endswith("_not_found") or exc.code.endswith("_missing"):
        status = 404
    elif "state" in exc.code or "conflict" in exc.code:
        status = 409
    else:
        status = 422
    return _error_response(status, exc.code, str(exc))


@app.exception_handler(ConfigurationError)
async def configuration_error(_: Request, exc: ConfigurationError) -> JSONResponse:
    return _error_response(503, "configuration_error", str(exc))


def services(request: Request) -> ApplicationServices:
    return request.app.state.services


def current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> dict[str, Any]:
    bearer = _bearer_token(authorization)
    return services(request).auth.authenticate(
        bearer_token=bearer,
        cookie_token=session_cookie,
    )


def admin_user(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    if not bool(user.get("is_admin")):
        raise AuthenticationError("administrator access required")
    return user


@app.get("/health")
def health(request: Request) -> dict[str, str]:
    with services(request).database.connect() as connection:
        connection.execute("select 1").fetchone()
    return {"status": "ok"}


@app.post("/api/v1/auth/github/device/start")
def github_device_start(request: Request) -> dict[str, Any]:
    return services(request).auth.start_github_device_login()


@app.post("/api/v1/auth/github/device/poll")
def github_device_poll(request: Request, payload: DevicePollRequest) -> dict[str, Any]:
    user, token = services(request).auth.poll_github_device_login(payload.device_code)
    return {
        "status": "authorized",
        "access_token": token,
        "token_type": "Bearer",
        "user": public_user_view(user),
    }


@app.post("/api/v1/auth/github/desktop/start")
def github_desktop_start(request: Request) -> dict[str, Any]:
    return services(request).auth.start_github_desktop_login()


@app.post("/api/v1/auth/github/desktop/poll")
def github_desktop_poll(request: Request, payload: DesktopAuthRequest) -> dict[str, Any]:
    user, token = services(request).auth.poll_github_desktop_login(
        flow_id=payload.flow_id,
        poll_secret=payload.poll_secret,
    )
    return {
        "status": "authorized",
        "access_token": token,
        "token_type": "Bearer",
        "user": public_user_view(user),
    }


@app.post("/api/v1/auth/github/desktop/cancel")
def github_desktop_cancel(request: Request, payload: DesktopAuthRequest) -> dict[str, str]:
    services(request).auth.cancel_github_desktop_login(
        flow_id=payload.flow_id,
        poll_secret=payload.poll_secret,
    )
    return {"status": "cancelled"}


@app.get("/api/v1/auth/github/login")
def github_login(
    request: Request,
    return_to: str | None = Query(default=None, max_length=2_000),
) -> RedirectResponse:
    service = services(request)
    url, state = service.auth.github_login_url(return_to=return_to)
    response = RedirectResponse(url, status_code=307)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=service.settings.oauth_state_ttl_seconds,
        secure=service.settings.base_url.startswith("https://"),
        httponly=True,
        samesite="lax",
        path="/api/v1/auth/github/callback",
    )
    return response


@app.get("/api/v1/auth/github/callback")
def github_callback(
    request: Request,
    code: str,
    state: str,
    state_cookie: Annotated[str | None, Cookie(alias=OAUTH_STATE_COOKIE)] = None,
) -> Response:
    service = services(request)
    completion = service.auth.complete_github_login(
        code=code,
        state=state,
        state_cookie=state_cookie,
    )
    if completion.flow_kind == "desktop":
        return FileResponse(
            Path(__file__).with_name("static") / "desktop_oauth_complete.html",
            media_type="text/html",
            headers={
                "Content-Security-Policy": (
                    "default-src 'none'; style-src 'unsafe-inline'; "
                    "img-src 'self'; frame-ancestors 'none'"
                )
            },
        )
    session_token = completion.session_token
    if not session_token:
        raise AuthenticationError("GitHub OAuth session was not created")
    response = RedirectResponse(
        completion.return_to or service.settings.github_success_redirect,
        status_code=303,
    )
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/api/v1/auth/github/callback")
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=service.settings.session_ttl_seconds,
        secure=service.settings.base_url.startswith("https://"),
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@app.get("/api/v1/auth/me")
def auth_me(user: Annotated[dict[str, Any], Depends(current_user)]) -> dict[str, Any]:
    return public_user_view(user)


@app.post("/api/v1/auth/logout")
def logout(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    session_cookie: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> JSONResponse:
    services(request).auth.delete_session(_bearer_token(authorization))
    services(request).auth.delete_session(session_cookie or "")
    response = JSONResponse({"status": "logged_out"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/api/v1/packages")
def list_packages(
    request: Request,
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return services(request).registry.list_packages(query=q, limit=limit, offset=offset)


@app.get("/api/v1/packages/{publisher}/{package_id}")
def package_detail(request: Request, publisher: str, package_id: str) -> dict[str, Any]:
    return services(request).registry.package_detail(publisher, package_id)


@app.get("/api/v1/releases/{release_id}")
def release_detail(request: Request, release_id: str) -> dict[str, Any]:
    return services(request).registry.release_detail(release_id)


@app.get("/api/v1/releases/{release_id}/download")
def release_download(request: Request, release_id: str) -> RedirectResponse:
    url = services(request).registry.download_url(release_id)
    return RedirectResponse(url, status_code=307)


@app.get("/api/v1/app-releases")
def list_app_releases(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    return services(request).app_releases.list_releases(
        include_private=False,
        limit=limit,
    )


@app.get("/api/v1/app-releases/latest")
def latest_app_release(request: Request) -> dict[str, Any]:
    return services(request).app_releases.latest_release()


@app.get("/api/v1/app-release-assets/{asset_id}/download")
def app_installer_download(request: Request, asset_id: str) -> RedirectResponse:
    url = services(request).app_releases.installer_download_url(asset_id)
    return RedirectResponse(url, status_code=307)


@app.get("/api/v1/app-releases/{app_release_id}")
def app_release_detail(request: Request, app_release_id: str) -> dict[str, Any]:
    return services(request).app_releases.release(
        app_release_id,
        include_private=False,
    )


@app.get("/api/v1/app-updates/{target}/{architecture}/{current_version}")
def app_update_manifest(
    request: Request,
    target: str,
    architecture: str,
    current_version: str,
) -> Response:
    manifest = services(request).app_releases.update_manifest(
        target=target,
        architecture=architecture,
        current_version=current_version,
    )
    if manifest is None:
        return Response(status_code=204)
    return JSONResponse(manifest)


@app.get("/api/v1/config/public")
def public_config(request: Request) -> dict[str, Any]:
    return services(request).app_releases.public_config()


@app.post("/api/v1/uploads", status_code=201)
def create_upload(
    request: Request,
    payload: UploadCreateRequest,
    user: Annotated[dict[str, Any], Depends(current_user)],
) -> dict[str, Any]:
    return services(request).registry.create_upload(
        user=user,
        filename=payload.filename,
        expected_size=payload.size_bytes,
    )


@app.post("/api/v1/uploads/{upload_id}/complete")
def complete_upload(
    request: Request,
    upload_id: str,
    user: Annotated[dict[str, Any], Depends(current_user)],
) -> dict[str, Any]:
    return services(request).registry.complete_upload(upload_id, user=user)


@app.get("/api/v1/uploads")
def list_uploads(
    request: Request,
    user: Annotated[dict[str, Any], Depends(current_user)],
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, Any]]:
    return services(request).registry.list_uploads(user=user, limit=limit)


@app.get("/api/v1/uploads/{upload_id}")
def upload_detail(
    request: Request,
    upload_id: str,
    user: Annotated[dict[str, Any], Depends(current_user)],
) -> dict[str, Any]:
    return services(request).registry.upload(upload_id, user=user)


@app.get("/api/v1/admin/releases/pending")
def pending_releases(
    request: Request,
    _: Annotated[dict[str, Any], Depends(admin_user)],
    limit: int = Query(default=100, ge=1, le=200),
) -> list[dict[str, Any]]:
    return services(request).registry.pending_releases(limit=limit)


@app.get("/api/v1/admin/releases/published")
def published_releases(
    request: Request,
    _: Annotated[dict[str, Any], Depends(admin_user)],
    limit: int = Query(default=100, ge=1, le=200),
) -> list[dict[str, Any]]:
    return services(request).registry.published_releases(limit=limit)


@app.post("/api/v1/admin/releases/{release_id}/approve")
def approve_release(
    request: Request,
    release_id: str,
    payload: ReviewRequest,
    admin: Annotated[dict[str, Any], Depends(admin_user)],
) -> dict[str, Any]:
    return services(request).registry.approve_release(
        release_id,
        admin=admin,
        review_message=payload.message,
    )


@app.post("/api/v1/admin/releases/{release_id}/reject")
def reject_release(
    request: Request,
    release_id: str,
    payload: ReviewRequest,
    admin: Annotated[dict[str, Any], Depends(admin_user)],
) -> dict[str, Any]:
    return services(request).registry.reject_release(
        release_id,
        admin=admin,
        review_message=payload.message,
    )


@app.post("/api/v1/admin/releases/{release_id}/unpublish")
def unpublish_release(
    request: Request,
    release_id: str,
    payload: ReviewRequest,
    admin: Annotated[dict[str, Any], Depends(admin_user)],
) -> dict[str, Any]:
    return services(request).registry.unpublish_release(
        release_id,
        admin=admin,
        review_message=payload.message,
    )


@app.get("/api/v1/admin/app-releases")
def admin_list_app_releases(
    request: Request,
    _: Annotated[dict[str, Any], Depends(admin_user)],
    limit: int = Query(default=50, ge=1, le=100),
) -> list[dict[str, Any]]:
    return services(request).app_releases.list_releases(
        include_private=True,
        limit=limit,
    )


@app.post("/api/v1/admin/app-releases", status_code=201)
def admin_create_app_release(
    request: Request,
    payload: AppReleaseCreateRequest,
    admin: Annotated[dict[str, Any], Depends(admin_user)],
) -> dict[str, Any]:
    return services(request).app_releases.create_release(
        admin=admin,
        version=payload.version,
        title=payload.title,
        notes_markdown=payload.notes_markdown,
    )


@app.get("/api/v1/admin/app-releases/{app_release_id}")
def admin_app_release_detail(
    request: Request,
    app_release_id: str,
    _: Annotated[dict[str, Any], Depends(admin_user)],
) -> dict[str, Any]:
    return services(request).app_releases.release(
        app_release_id,
        include_private=True,
    )


@app.put("/api/v1/admin/app-releases/{app_release_id}")
def admin_update_app_release(
    request: Request,
    app_release_id: str,
    payload: AppReleaseUpdateRequest,
    admin: Annotated[dict[str, Any], Depends(admin_user)],
) -> dict[str, Any]:
    return services(request).app_releases.update_release(
        app_release_id,
        admin=admin,
        title=payload.title,
        notes_markdown=payload.notes_markdown,
    )


@app.delete(
    "/api/v1/admin/app-releases/{app_release_id}",
    status_code=204,
)
def admin_delete_app_release(
    request: Request,
    app_release_id: str,
    admin: Annotated[dict[str, Any], Depends(admin_user)],
) -> Response:
    services(request).app_releases.delete_release(
        app_release_id,
        admin=admin,
    )
    return Response(status_code=204)


@app.post(
    "/api/v1/admin/app-releases/{app_release_id}/assets",
    status_code=201,
)
def admin_create_app_release_asset(
    request: Request,
    app_release_id: str,
    payload: AppReleaseAssetCreateRequest,
    admin: Annotated[dict[str, Any], Depends(admin_user)],
) -> dict[str, Any]:
    return services(request).app_releases.create_asset_upload(
        app_release_id,
        admin=admin,
        asset_kind=payload.asset_kind,
        platform=payload.platform,
        architecture=payload.architecture,
        filename=payload.filename,
        expected_size=payload.size_bytes,
        updater_signature=payload.updater_signature,
    )


@app.post(
    "/api/v1/admin/app-releases/{app_release_id}/assets/{asset_id}/complete"
)
def admin_complete_app_release_asset(
    request: Request,
    app_release_id: str,
    asset_id: str,
    admin: Annotated[dict[str, Any], Depends(admin_user)],
) -> dict[str, Any]:
    return services(request).app_releases.complete_asset_upload(
        app_release_id,
        asset_id,
        admin=admin,
    )


@app.delete(
    "/api/v1/admin/app-releases/{app_release_id}/assets/{asset_id}",
    status_code=204,
)
def admin_delete_app_release_asset(
    request: Request,
    app_release_id: str,
    asset_id: str,
    admin: Annotated[dict[str, Any], Depends(admin_user)],
) -> Response:
    services(request).app_releases.delete_asset(
        app_release_id,
        asset_id,
        admin=admin,
    )
    return Response(status_code=204)


@app.post("/api/v1/admin/app-releases/{app_release_id}/publish")
def admin_publish_app_release(
    request: Request,
    app_release_id: str,
    admin: Annotated[dict[str, Any], Depends(admin_user)],
) -> dict[str, Any]:
    return services(request).app_releases.queue_publish(
        app_release_id,
        admin=admin,
    )


def _error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, credentials = authorization.partition(" ")
    return credentials.strip() if scheme.casefold() == "bearer" else ""
