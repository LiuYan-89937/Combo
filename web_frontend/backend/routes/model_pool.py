from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, HTTPException

from agent_factory.local_inference import (
    inspect_rocm_runtime,
    LocalInferenceRuntimeManager,
)
from agent_factory.model_pool import (
    LocalModelArtifact,
    ModelPoolProfile,
    ModelPoolSelector,
    ModelPoolStore,
    ModelStorage,
    ModelUsageStore,
    ModelSelectionRequest,
    list_local_inference_engines,
)
from agent_factory.model_pool.store import ModelPoolStoreError
from agent_factory.models import reset_chat_models, reset_embedding_model


def create_model_pool_router(runtime_manager: LocalInferenceRuntimeManager) -> APIRouter:
    router = APIRouter(prefix="/api/model-pool")

    @router.get("/engines")
    async def list_engines():
        return {"engines": list_local_inference_engines()}

    @router.get("/runtime/rocm")
    async def rocm_runtime():
        return inspect_rocm_runtime(require_available=False).payload()

    @router.get("/runtimes")
    async def inference_runtimes():
        rocm = await asyncio.to_thread(inspect_rocm_runtime, require_available=False)
        return {"runtimes": runtime_manager.states(), "rocm": rocm.payload()}

    @router.get("/defaults")
    async def default_profiles():
        return {"defaults": ModelPoolStore().default_profile_ids()}

    @router.get("/storage")
    async def model_storage():
        storage = ModelStorage()
        return {
            "root_path": str(storage.root),
            "modelscope_cache_path": str(storage.modelscope_cache),
            "directories": [item.payload() for item in storage.list_model_directories()],
        }

    @router.put("/defaults/{role}")
    async def set_default_profile(role: str, payload: dict[str, Any]):
        try:
            requested_profile_id = str(payload.get("profile_id") or "").strip()
            if requested_profile_id and not runtime_manager.is_ready(requested_profile_id):
                raise ValueError("model must finish loading before it can be set as default")
            profile_id = ModelPoolStore().set_default_profile_id(
                role=role,
                profile_id=requested_profile_id or None,
            )
            _reset_model_caches()
        except Exception as exc:
            raise _http_error(exc) from exc
        return {"role": role, "profile_id": profile_id}

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
            if profile.enabled:
                store.disable_other_profiles(profile.kind, profile.profile_id)
            artifact = store.get_artifact(profile.artifact_id)
            runtime = await _apply_runtime_intent(runtime_manager, profile)
            _reset_model_caches()
        except Exception as exc:
            raise _http_error(exc) from exc
        return {
            "profile": profile.to_public(artifact).model_dump(mode="json"),
            "runtime": runtime,
        }

    @router.patch("/profiles/{profile_id}")
    async def patch_profile(profile_id: str, payload: dict[str, Any]):
        store = ModelPoolStore()
        try:
            profile = store.patch_profile(profile_id, payload)
            if profile.enabled:
                store.disable_other_profiles(profile.kind, profile.profile_id)
            artifact = store.get_artifact(profile.artifact_id)
            runtime = await _apply_runtime_intent(runtime_manager, profile)
            _reset_model_caches()
        except Exception as exc:
            raise _http_error(exc) from exc
        return {
            "profile": profile.to_public(artifact).model_dump(mode="json"),
            "runtime": runtime,
        }

    @router.delete("/profiles/{profile_id}")
    async def delete_profile(profile_id: str):
        await runtime_manager.unload(profile_id)
        deleted = ModelPoolStore().delete_profile(profile_id)
        if deleted:
            _reset_model_caches()
        return {"deleted": deleted}

    @router.post("/profiles/{profile_id}/load")
    async def load_profile(profile_id: str):
        try:
            return {"runtime": await runtime_manager.load(profile_id)}
        except Exception as exc:
            raise _http_error(exc) from exc

    @router.post("/profiles/{profile_id}/unload")
    async def unload_profile(profile_id: str):
        try:
            return {"runtime": await runtime_manager.unload(profile_id)}
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


async def _apply_runtime_intent(
    runtime_manager: LocalInferenceRuntimeManager,
    profile: ModelPoolProfile,
) -> dict[str, Any]:
    if profile.enabled:
        return await runtime_manager.load(profile.profile_id)
    return await runtime_manager.unload(profile.profile_id)


def _artifact_from_payload(payload: dict[str, Any], *, store: ModelPoolStore) -> LocalModelArtifact:
    data = dict(payload)
    storage = ModelStorage()
    data["local_path"] = str(storage.require_model_directory(str(data.get("local_path") or "")))
    tokenizer_path = str(data.get("tokenizer_path") or "").strip()
    if tokenizer_path:
        data["tokenizer_path"] = str(storage.resolve_directory(tokenizer_path))
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


def _http_error(exc: Exception) -> HTTPException:
    status = 404 if isinstance(exc, ModelPoolStoreError) and str(exc).startswith("unknown ") else 400
    return HTTPException(status_code=status, detail=f"{type(exc).__name__}: {exc}")


def _reset_model_caches() -> None:
    reset_chat_models()
    reset_embedding_model()


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
