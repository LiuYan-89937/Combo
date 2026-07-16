from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from fastapi import FastAPI, HTTPException

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.local_inference.memory_budget import (
    estimate_inference_memory,
    warm_inference_memory_metadata,
)
from agent_factory.local_inference.implementation import inspect_llama_implementations
from agent_factory.local_inference.node_control import (
    InferenceMemoryEstimateRequest,
    InferenceNodeAction,
    InferenceNodeProfileConfiguration,
)
from agent_factory.local_inference.rocm import inspect_rocm_runtime
from agent_factory.local_inference.runtime_manager import LocalInferenceRuntimeManager
from agent_factory.model_pool.schema import (
    LlamaCppInferenceConfig,
    ModelPoolProfile,
    StableDiffusionCppInferenceConfig,
    TransformersInferenceConfig,
)
from agent_factory.model_pool.store import ModelPoolStore


def create_app() -> FastAPI:
    runtime_manager = LocalInferenceRuntimeManager(
        allow_external_control=False,
        restore_enabled_fallback=False,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        await asyncio.to_thread(_warm_enabled_model_metadata)
        await runtime_manager.restore()
        try:
            yield
        finally:
            await runtime_manager.shutdown()

    app = FastAPI(title="FastAgentFactory Inference Node", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/runtime/rocm")
    async def rocm_runtime() -> dict[str, Any]:
        return inspect_rocm_runtime(require_available=False).payload()

    @app.get("/runtime/software")
    async def runtime_software() -> dict[str, Any]:
        return _software_payload()

    @app.get("/runtime/llama")
    async def llama_runtime() -> dict[str, Any]:
        return inspect_llama_implementations().model_dump(mode="json")

    @app.get("/runtimes")
    async def runtimes() -> dict[str, Any]:
        return {"runtimes": [_runtime_payload(item) for item in runtime_manager.states()]}

    @app.get("/models")
    async def models() -> dict[str, Any]:
        store = ModelPoolStore()
        rocm = inspect_rocm_runtime(require_available=False)
        device = rocm.devices[0] if rocm.devices else None
        runtime_by_profile = {
            str(item.get("profile_id") or ""): item
            for item in runtime_manager.states()
            if str(item.get("profile_id") or "")
        }
        result: list[dict[str, Any]] = []
        for profile in store.list_profiles(enabled=True):
            artifact = store.require_artifact(profile.artifact_id)
            runtime = runtime_by_profile.get(profile.profile_id, {})
            size_bytes = None
            if artifact.local_path:
                path = artifact.resolved_path()
                size_bytes = path.stat().st_size if path.is_file() else None
            capabilities = (
                ["embedding"]
                if profile.kind == "embedding"
                else ["image_generation"]
                if profile.kind == "image_generation"
                else ["completion"]
            )
            if "image" in profile.capabilities.input_modalities:
                capabilities.append("multimodal")
            model_payload = {
                    "model_id": profile.served_model_name,
                    "kind": profile.kind,
                    "format": artifact.model_format,
                    "context_length": profile.limits.max_input_tokens,
                    "parameter_count": None,
                    "size_bytes": size_bytes,
                    "embedding_dimensions": profile.embedding_dimensions,
                    "capabilities": capabilities,
                    "phase": str(runtime.get("phase") or "idle"),
                    "profile_id": profile.profile_id,
                    "engine": profile.engine,
                    "revision": artifact.revision,
                    "checksum": artifact.checksum,
                    "runtime_configuration": _runtime_configuration(profile),
                }
            if profile.kind == "chat":
                model_payload["memory_estimate"] = estimate_inference_memory(
                    profile=profile,
                    artifact=artifact,
                    requested=InferenceNodeProfileConfiguration.from_profile(profile),
                    runtime=runtime,
                    device=device,
                ).payload()
            result.append(model_payload)
        return {"models": result}

    @app.post("/models/memory-estimate")
    async def memory_estimate(request: InferenceMemoryEstimateRequest) -> dict[str, Any]:
        profile = _resolve_profile_identity(request.kind, request.model_id)
        artifact = ModelPoolStore().require_artifact(profile.artifact_id)
        runtime = runtime_manager.state_for_profile(profile.profile_id)
        rocm = inspect_rocm_runtime(require_available=False)
        device = rocm.devices[0] if rocm.devices else None
        estimate = estimate_inference_memory(
            profile=profile,
            artifact=artifact,
            requested=request.profile,
            runtime=runtime,
            device=device,
        )
        return {"estimate": estimate.payload()}

    @app.post("/runtimes/load")
    async def load_runtime(request: InferenceNodeAction) -> dict[str, Any]:
        profile = _resolve_profile(request, apply_configuration=True)
        return {"runtime": _runtime_payload(await runtime_manager.load(profile.profile_id))}

    @app.post("/runtimes/unload")
    async def unload_runtime(request: InferenceNodeAction) -> dict[str, Any]:
        profile = _resolve_profile(request)
        return {"runtime": _runtime_payload(await runtime_manager.unload(profile.profile_id), profile=profile)}

    @app.post("/runtimes/restart")
    async def restart_runtime(request: InferenceNodeAction) -> dict[str, Any]:
        profile = _resolve_profile(request, apply_configuration=True)
        return {"runtime": _runtime_payload(await runtime_manager.restart(profile.profile_id))}

    return app


def _resolve_profile(
    request: InferenceNodeAction,
    *,
    apply_configuration: bool = False,
) -> ModelPoolProfile:
    profile = _resolve_profile_identity(request.kind, request.model_id)
    if apply_configuration and request.profile is not None:
        profile = _apply_profile_configuration(profile, request.profile)
    return profile


def _resolve_profile_identity(kind: str, model_id: str) -> ModelPoolProfile:
    profiles = [
        profile
        for profile in ModelPoolStore().list_profiles(kind=kind, enabled=True)
        if profile.served_model_name == model_id
    ]
    if len(profiles) != 1:
        raise HTTPException(
            status_code=404,
            detail=f"enabled {kind} model is not registered on the inference node: {model_id}",
        )
    return profiles[0]


def _apply_profile_configuration(
    profile: ModelPoolProfile,
    configuration: InferenceNodeProfileConfiguration,
) -> ModelPoolProfile:
    inference = configuration.inference
    if profile.kind == "chat" and inference is not None and not isinstance(
        inference,
        LlamaCppInferenceConfig,
    ):
        raise ValueError("chat inference nodes require llama.cpp settings")
    if profile.kind == "embedding" and inference is not None and not isinstance(
        inference,
        TransformersInferenceConfig,
    ):
        raise ValueError("embedding inference nodes require Transformers settings")
    if profile.kind == "image_generation" and inference is not None and not isinstance(
        inference,
        StableDiffusionCppInferenceConfig,
    ):
        raise ValueError("image generation inference nodes require stable-diffusion.cpp settings")

    payload = profile.model_dump(mode="json")
    payload.update(
        {
            "limits": configuration.limits.model_dump(mode="json"),
            "capabilities": configuration.capabilities.model_dump(mode="json"),
            "embedding_dimensions": configuration.embedding_dimensions,
            "normalize_embeddings": configuration.normalize_embeddings,
        }
    )
    if inference is not None:
        payload["inference"] = {
            **profile.inference.model_dump(mode="json"),
            **inference.model_dump(mode="json", exclude_none=True),
        }
    updated = ModelPoolProfile.model_validate(payload)
    return ModelPoolStore().upsert_profile(updated)


def _runtime_payload(
    runtime: dict[str, Any],
    *,
    profile: ModelPoolProfile | None = None,
) -> dict[str, Any]:
    profile_id = str(runtime.get("profile_id") or "")
    resolved = profile or (ModelPoolStore().get_profile(profile_id) if profile_id else None)
    return {
        **runtime,
        "served_model_name": resolved.served_model_name if resolved else "",
    }


def _runtime_configuration(profile: ModelPoolProfile) -> dict[str, Any]:
    configuration = profile.inference.model_dump(mode="json")
    mmproj_path = configuration.pop("mmproj_path", None)
    if mmproj_path is not None:
        configuration["multimodal_projector"] = bool(mmproj_path)
    return configuration


def _software_payload() -> dict[str, Any]:
    configured_binary = str(os.environ.get("AGENTFACTORY_LLAMA_SERVER_PATH") or "llama-server").strip()
    binary = shutil.which(configured_binary)
    configured_sd_binary = str(os.environ.get("AGENTFACTORY_SD_SERVER_PATH") or "sd-server").strip()
    sd_binary = shutil.which(configured_sd_binary)
    implementation = inspect_llama_implementations()
    return {
        "python_version": sys.version.split()[0],
        "project_revision": _command_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
        ),
        "llama_server_version": _command_output([binary, "--version"]) if binary else "",
        "llama_implementation": implementation.model_dump(mode="json"),
        "sd_server_version": _command_output([sd_binary, "--version"]) if sd_binary else "",
    }


def _warm_enabled_model_metadata() -> None:
    store = ModelPoolStore()
    for profile in store.list_profiles(kind="chat", enabled=True):
        warm_inference_memory_metadata(store.require_artifact(profile.artifact_id))


def _command_output(command: list[str], *, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Radeon inference node control service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8004)
    args = parser.parse_args()
    load_agentfactory_dotenv()
    import uvicorn

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
