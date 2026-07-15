from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, HTTPException
import httpx

from agent_factory.local_inference.rocm import inspect_rocm_runtime
from agent_factory.local_inference.runtime_manager import LocalInferenceRuntimeManager
from agent_factory.local_inference.config import (
    load_inference_runtime_mode,
    load_inference_telemetry_endpoint,
    load_local_inference_endpoint,
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
        if load_inference_runtime_mode() == "external":
            return await _external_rocm_payload()
        return inspect_rocm_runtime(require_available=False).payload()

    @router.get("/runtimes")
    async def inference_runtimes():
        if load_inference_runtime_mode() == "external":
            rocm_payload = await _external_rocm_payload()
        else:
            rocm = await asyncio.to_thread(inspect_rocm_runtime, require_available=False)
            rocm_payload = rocm.payload()
        return {"runtimes": runtime_manager.states(), "rocm": rocm_payload}

    @router.get("/defaults")
    async def default_profiles():
        return {"defaults": ModelPoolStore().default_profile_ids()}

    @router.get("/storage")
    async def model_storage():
        mode = load_inference_runtime_mode()
        if mode == "external":
            try:
                remote_models = await _external_model_list()
                remote_error = ""
            except (httpx.HTTPError, ValueError) as exc:
                remote_models = []
                remote_error = f"{type(exc).__name__}: {exc}"
            return {
                "inference_mode": mode,
                "root_path": "",
                "modelscope_cache_path": "",
                "directories": [],
                "remote_models": remote_models,
                "remote_error": remote_error,
            }
        storage = ModelStorage()
        return {
            "inference_mode": mode,
            "root_path": str(storage.root),
            "modelscope_cache_path": str(storage.modelscope_cache),
            "directories": [item.payload() for item in storage.list_model_directories()],
            "remote_models": [],
            "remote_error": "",
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
        store = ModelPoolStore()
        try:
            existing = store.require_artifact(artifact_id)
            merged = {**existing.model_dump(mode="json"), **dict(payload), "artifact_id": artifact_id}
            artifact = store.upsert_artifact(_artifact_from_payload(merged, store=store))
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

    @router.post("/profiles/{profile_id}/restart")
    async def restart_profile(profile_id: str):
        try:
            return {"runtime": await runtime_manager.restart(profile_id)}
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
    if str(data.get("source") or "local_storage") == "external_endpoint":
        data["source"] = "external_endpoint"
        data["local_path"] = None
        external_model_id = str(data.get("external_model_id") or "").strip()
        data["external_model_id"] = external_model_id
        if not str(data.get("artifact_id") or "").strip():
            data["artifact_id"] = _unique_id(
                _slug(str(data.get("display_name") or external_model_id or "model")),
                existing={item.artifact_id for item in store.list_artifacts()},
                salt=external_model_id,
            )
        return LocalModelArtifact.model_validate(data)
    storage = ModelStorage()
    data["source"] = "local_storage"
    data["external_model_id"] = None
    kind = str(data.get("kind") or "").strip().lower()
    if kind == "chat":
        data["model_format"] = "llama_cpp"
        data["local_path"] = str(storage.require_llama_model_file(str(data.get("local_path") or "")))
    else:
        data["model_format"] = "transformers"
        data["local_path"] = str(storage.require_model_directory(str(data.get("local_path") or "")))
    if not str(data.get("artifact_id") or "").strip():
        data["artifact_id"] = _unique_id(
            _slug(str(data.get("display_name") or Path(str(data.get("local_path") or "model")).name)),
            existing={item.artifact_id for item in store.list_artifacts()},
            salt=str(data.get("local_path") or ""),
        )
    return LocalModelArtifact.model_validate(data)


async def _external_model_list() -> list[dict[str, Any]]:
    endpoint = load_local_inference_endpoint(timeout_seconds=5.0)
    async with httpx.AsyncClient(timeout=endpoint.timeout_seconds) as client:
        response = await client.get(endpoint.endpoint("/models"))
        response.raise_for_status()
        payload = response.json()
    models = payload.get("data") if isinstance(payload, dict) else None
    result: list[dict[str, Any]] = []
    for item in models or []:
        if not isinstance(item, dict) or not str(item.get("id") or "").strip():
            continue
        meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
        result.append(
            {
                "model_id": str(item["id"]),
                "format": str(meta.get("ftype") or ""),
                "context_length": meta.get("n_ctx"),
                "parameter_count": meta.get("n_params"),
                "size_bytes": meta.get("size"),
            }
        )
    return result


async def _external_rocm_payload() -> dict[str, Any]:
    endpoint = load_inference_telemetry_endpoint(timeout_seconds=5.0)
    try:
        async with httpx.AsyncClient(timeout=endpoint.timeout_seconds) as client:
            response = await client.get(endpoint.endpoint("/runtime/rocm"))
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict):
            return payload
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "available": False,
            "torch_version": "",
            "hip_version": "",
            "rocm_version": "",
            "device_count": 0,
            "devices": [],
            "telemetry_source": "external",
            "error": f"{type(exc).__name__}: {exc}",
        }
    raise ValueError("external telemetry response must be a JSON object")


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
