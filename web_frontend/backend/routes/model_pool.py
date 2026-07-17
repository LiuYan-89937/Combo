from __future__ import annotations

import asyncio
import hashlib
import re
from time import perf_counter
from typing import Any

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage

from agent_factory.model_pool import (
    ModelPoolCredential,
    ModelPoolProfile,
    ModelPoolSelector,
    ModelPoolStore,
    ModelUsageStore,
    ModelSelectionRequest,
    list_model_pool_provider_profiles,
)
from agent_factory.model_pool.resolver import resolve_chat_model_profile
from agent_factory.model_pool.schema import ModelProfileBinding
from agent_factory.model_pool.store import ModelPoolStoreError


def create_model_pool_router() -> APIRouter:
    router = APIRouter(prefix="/api/model-pool")

    @router.get("/providers")
    def list_providers():
        return {"providers": list_model_pool_provider_profiles()}

    @router.get("/credentials")
    def list_credentials():
        store = ModelPoolStore()
        return {"credentials": [item.to_public().model_dump(mode="json") for item in store.list_credentials()]}

    @router.post("/credentials")
    def upsert_credential(payload: dict[str, Any]):
        store = ModelPoolStore()
        try:
            credential = store.upsert_credential(_credential_from_payload(payload, store=store))
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"credential": credential.to_public().model_dump(mode="json")}

    @router.patch("/credentials/{credential_id}")
    def patch_credential(credential_id: str, payload: dict[str, Any]):
        store = ModelPoolStore()
        try:
            credential = store.patch_credential(credential_id, payload)
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"credential": credential.to_public().model_dump(mode="json")}

    @router.delete("/credentials/{credential_id}")
    def delete_credential(credential_id: str):
        store = ModelPoolStore()
        try:
            return {"deleted": store.delete_credential(credential_id)}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/profiles")
    def list_profiles(kind: str | None = None):
        store = ModelPoolStore()
        credentials = {item.credential_id: item for item in store.list_credentials()}
        profile_kind = (kind or "").strip().lower() or None
        if profile_kind not in {None, "chat", "image_generation"}:
            raise HTTPException(status_code=400, detail="unsupported model profile kind")
        profiles = [
            profile.to_public(credentials.get(profile.credential_id)).model_dump(mode="json")
            for profile in store.list_profiles(kind=profile_kind)
        ]
        return {"profiles": profiles}

    @router.get("/usage")
    async def usage_summary(group_by: str = "model", days: int = 14):
        value = group_by.strip().lower()
        if value not in {"model", "provider", "agent"}:
            raise HTTPException(status_code=400, detail="unsupported usage group_by")
        return ModelUsageStore().summary(group_by=value, days=days)

    @router.post("/profiles")
    def upsert_profile(payload: dict[str, Any]):
        store = ModelPoolStore()
        try:
            profile = store.upsert_profile(_profile_from_payload(payload, store=store))
            credential = store.get_credential(profile.credential_id)
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"profile": profile.to_public(credential).model_dump(mode="json")}

    @router.patch("/profiles/{profile_id}")
    def patch_profile(profile_id: str, payload: dict[str, Any]):
        store = ModelPoolStore()
        try:
            profile = store.patch_profile(profile_id, payload)
            credential = store.get_credential(profile.credential_id)
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"profile": profile.to_public(credential).model_dump(mode="json")}

    @router.delete("/profiles/{profile_id}")
    def delete_profile(profile_id: str):
        return {"deleted": ModelPoolStore().delete_profile(profile_id)}

    @router.post("/profiles/{profile_id}/ping")
    async def ping_profile(profile_id: str):
        store = ModelPoolStore()
        try:
            profile = store.require_profile(profile_id)
            if profile.kind != "chat":
                raise ValueError("connection testing currently supports chat model profiles only")
            result = await asyncio.to_thread(_ping_chat_profile, profile_id, store)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=_probe_error_detail(exc)) from exc
        return result

    @router.post("/profiles/delete")
    def delete_profiles(payload: dict[str, Any]):
        ids = [str(item).strip() for item in payload.get("profile_ids", []) if str(item).strip()]
        store = ModelPoolStore()
        return {"deleted": {profile_id: store.delete_profile(profile_id) for profile_id in ids}}

    @router.post("/select")
    def select_models(payload: dict[str, Any]):
        try:
            request = ModelSelectionRequest.model_validate(payload)
            result = ModelPoolSelector().select(request)
        except Exception as exc:
            raise _http_error(exc) from exc
        return result.model_dump(mode="json")

    return router


def _credential_from_payload(payload: dict[str, Any], *, store: ModelPoolStore) -> ModelPoolCredential:
    data = dict(payload)
    if not str(data.get("credential_id") or "").strip():
        data["credential_id"] = _unique_id(
            _slug(str(data.get("display_name") or data.get("provider") or "credential")),
            existing={item.credential_id for item in store.list_credentials()},
            salt=str(data.get("base_url") or data.get("provider") or ""),
        )
    return ModelPoolCredential.model_validate(data)


def _profile_from_payload(payload: dict[str, Any], *, store: ModelPoolStore) -> ModelPoolProfile:
    data = dict(payload)
    requested_kind = str(data.get("kind") or "chat").strip().lower()
    if requested_kind not in {"chat", "image_generation"}:
        raise ValueError("unsupported model profile kind")
    data["kind"] = requested_kind
    if not str(data.get("profile_id") or "").strip():
        data["profile_id"] = _unique_id(
            _slug(str(data.get("display_name") or data.get("model_name") or "model")),
            existing={item.profile_id for item in store.list_profiles()},
            salt=str(data.get("provider") or "") + ":" + str(data.get("model_name") or ""),
        )
    return ModelPoolProfile.model_validate(data)


def _http_error(exc: Exception) -> HTTPException:
    status = 404 if isinstance(exc, ModelPoolStoreError) and str(exc).startswith("unknown ") else 400
    return HTTPException(status_code=status, detail=f"{type(exc).__name__}: {exc}")


def _ping_chat_profile(profile_id: str, store: ModelPoolStore) -> dict[str, Any]:
    resolved = resolve_chat_model_profile(
        ModelProfileBinding(profile_id=profile_id, selection_source="manual", reason="model pool connection test"),
        role="connection_test",
        store=store,
    )
    started_at = perf_counter()
    response = resolved.model.invoke([HumanMessage(content="HelloWorld")])
    latency_ms = round((perf_counter() - started_at) * 1000)
    content = _response_text(response)
    return {
        "status": "ok",
        "profile_id": profile_id,
        "latency_ms": latency_ms,
        "response_preview": content[:500],
    }


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(item.get("text") or "") if isinstance(item, dict) else str(item) for item in content)
    return str(content)


def _probe_error_detail(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    return re.sub(r"(?i)(api[_-]?key|authorization)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", message)


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip().lower()).strip("_.-")
    text = re.sub(r"_+", "_", text)
    if not text or not text[0].isalpha():
        text = f"model_{text or 'profile'}"
    return text[:80]


def _unique_id(base: str, *, existing: set[str], salt: str) -> str:
    candidate = base
    if candidate not in existing:
        return candidate
    digest = hashlib.sha1(f"{base}:{salt}".encode("utf-8")).hexdigest()[:8]
    candidate = f"{base}_{digest}"
    index = 2
    while candidate in existing:
        candidate = f"{base}_{digest}_{index}"
        index += 1
    return candidate
