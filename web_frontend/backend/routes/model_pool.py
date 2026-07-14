from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from agent_factory.local_inference import (
    inspect_rocm_runtime,
    load_local_embedding_endpoint,
    load_local_inference_endpoint,
)
from agent_factory.model_pool import (
    LocalModelArtifact,
    ModelPoolProfile,
    ModelPoolSelector,
    ModelPoolStore,
    ModelUsageStore,
    ModelSelectionRequest,
    list_local_inference_engines,
)
from agent_factory.model_pool.store import ModelPoolStoreError


def create_model_pool_router() -> APIRouter:
    router = APIRouter(prefix="/api/model-pool")

    @router.get("/engines")
    async def list_engines():
        return {"engines": list_local_inference_engines()}

    @router.get("/runtime/rocm")
    async def rocm_runtime():
        return inspect_rocm_runtime(require_available=False).payload()

    @router.get("/artifacts")
    async def list_artifacts():
        return {"artifacts": [item.model_dump(mode="json") for item in ModelPoolStore().list_artifacts()]}

    @router.post("/artifacts")
    async def upsert_artifact(payload: dict[str, Any]):
        store = ModelPoolStore()
        try:
            artifact = store.upsert_artifact(_artifact_from_payload(payload, store=store))
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"artifact": artifact.model_dump(mode="json")}

    @router.patch("/artifacts/{artifact_id}")
    async def patch_artifact(artifact_id: str, payload: dict[str, Any]):
        try:
            artifact = ModelPoolStore().patch_artifact(artifact_id, payload)
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"artifact": artifact.model_dump(mode="json")}

    @router.delete("/artifacts/{artifact_id}")
    async def delete_artifact(artifact_id: str):
        try:
            return {"deleted": ModelPoolStore().delete_artifact(artifact_id)}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/profiles")
    async def list_profiles(kind: str | None = None):
        profile_kind = (kind or "").strip().lower() or None
        if profile_kind not in {None, "chat", "embedding"}:
            raise HTTPException(status_code=400, detail="unsupported local model profile kind")
        store = ModelPoolStore()
        artifacts = {item.artifact_id: item for item in store.list_artifacts()}
        return {
            "profiles": [
                profile.to_public(artifacts.get(profile.artifact_id)).model_dump(mode="json")
                for profile in store.list_profiles(kind=profile_kind)
            ]
        }

    @router.post("/profiles")
    async def upsert_profile(payload: dict[str, Any]):
        store = ModelPoolStore()
        try:
            profile = store.upsert_profile(_profile_from_payload(payload, store=store))
            artifact = store.get_artifact(profile.artifact_id)
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"profile": profile.to_public(artifact).model_dump(mode="json")}

    @router.patch("/profiles/{profile_id}")
    async def patch_profile(profile_id: str, payload: dict[str, Any]):
        store = ModelPoolStore()
        try:
            profile = store.patch_profile(profile_id, payload)
            artifact = store.get_artifact(profile.artifact_id)
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"profile": profile.to_public(artifact).model_dump(mode="json")}

    @router.delete("/profiles/{profile_id}")
    async def delete_profile(profile_id: str):
        return {"deleted": ModelPoolStore().delete_profile(profile_id)}

    @router.post("/profiles/{profile_id}/check")
    async def check_profile(profile_id: str):
        store = ModelPoolStore()
        try:
            profile = store.require_profile(profile_id)
            artifact = store.require_artifact(profile.artifact_id)
            path = artifact.resolved_path()
            result: dict[str, Any] = {
                "status": "ready" if path.is_dir() else "missing",
                "profile_id": profile.profile_id,
                "artifact_id": artifact.artifact_id,
                "local_path": str(path),
                "path_exists": path.is_dir(),
                "engine": profile.engine,
            }
            if profile.kind == "chat" and path.is_dir():
                result["runtime"] = await _chat_runtime_status(profile.served_model_name)
            elif profile.kind == "embedding" and path.is_dir():
                result["runtime"] = await _embedding_runtime_status(profile.profile_id)
            return result
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.get("/usage")
    async def usage_summary(group_by: str = "model", days: int = 14):
        value = group_by.strip().lower()
        if value not in {"model", "provider", "agent"}:
            raise HTTPException(status_code=400, detail="unsupported usage group_by")
        return ModelUsageStore().summary(group_by=value, days=days)

    @router.post("/select")
    async def select_models(payload: dict[str, Any]):
        try:
            result = ModelPoolSelector().select(ModelSelectionRequest.model_validate(payload))
        except Exception as exc:
            raise _http_error(exc) from exc
        return result.model_dump(mode="json")

    return router


def _artifact_from_payload(payload: dict[str, Any], *, store: ModelPoolStore) -> LocalModelArtifact:
    data = dict(payload)
    if not str(data.get("artifact_id") or "").strip():
        data["artifact_id"] = _unique_id(
            _slug(str(data.get("display_name") or Path(str(data.get("local_path") or "model")).name)),
            existing={item.artifact_id for item in store.list_artifacts()},
            salt=str(data.get("local_path") or ""),
        )
    return LocalModelArtifact.model_validate(data)


def _profile_from_payload(payload: dict[str, Any], *, store: ModelPoolStore) -> ModelPoolProfile:
    data = dict(payload)
    if not str(data.get("profile_id") or "").strip():
        data["profile_id"] = _unique_id(
            _slug(str(data.get("display_name") or data.get("served_model_name") or "local_model")),
            existing={item.profile_id for item in store.list_profiles()},
            salt=str(data.get("artifact_id") or "") + ":" + str(data.get("engine") or ""),
        )
    return ModelPoolProfile.model_validate(data)


async def _chat_runtime_status(model_name: str) -> dict[str, Any]:
    endpoint = load_local_inference_endpoint()
    async with httpx.AsyncClient(timeout=endpoint.timeout_seconds) as client:
        response = await client.get(endpoint.endpoint("/models"))
        response.raise_for_status()
        body = response.json()
    models = body.get("data") if isinstance(body, dict) else None
    names = [str(item.get("id") or "") for item in models or [] if isinstance(item, dict)]
    return {
        "status": "ready" if model_name in names else "model_not_served",
        "served_models": names,
    }


async def _embedding_runtime_status(profile_id: str) -> dict[str, Any]:
    endpoint = load_local_embedding_endpoint()
    async with httpx.AsyncClient(timeout=endpoint.timeout_seconds) as client:
        response = await client.get(endpoint.endpoint("/health"))
        response.raise_for_status()
        body = response.json()
    loaded_profile_id = str(body.get("profile_id") or "") if isinstance(body, dict) else ""
    return {
        "status": "ready" if loaded_profile_id == profile_id else "profile_not_loaded",
        "loaded_profile_id": loaded_profile_id,
        "dimensions": body.get("dimensions") if isinstance(body, dict) else None,
    }


def _http_error(exc: Exception) -> HTTPException:
    status = 404 if isinstance(exc, ModelPoolStoreError) and str(exc).startswith("unknown ") else 400
    return HTTPException(status_code=status, detail=f"{type(exc).__name__}: {exc}")


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip().lower()).strip("_.-")
    text = re.sub(r"_+", "_", text)
    if not text or not text[0].isalpha():
        text = f"model_{text or 'profile'}"
    return text[:80]


def _unique_id(base: str, *, existing: set[str], salt: str) -> str:
    if base not in existing:
        return base
    digest = hashlib.sha1(f"{base}:{salt}".encode("utf-8")).hexdigest()[:8]
    candidate = f"{base}_{digest}"
    index = 2
    while candidate in existing:
        candidate = f"{base}_{digest}_{index}"
        index += 1
    return candidate
