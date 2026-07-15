from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.local_inference.node_control import InferenceNodeAction
from agent_factory.local_inference.rocm import inspect_rocm_runtime
from agent_factory.local_inference.runtime_manager import LocalInferenceRuntimeManager
from agent_factory.model_pool.schema import ModelPoolProfile
from agent_factory.model_pool.store import ModelPoolStore


def create_app() -> FastAPI:
    runtime_manager = LocalInferenceRuntimeManager(
        allow_external_control=False,
        restore_enabled_fallback=False,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
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

    @app.get("/runtimes")
    async def runtimes() -> dict[str, Any]:
        return {"runtimes": [_runtime_payload(item) for item in runtime_manager.states()]}

    @app.get("/models")
    async def models() -> dict[str, Any]:
        store = ModelPoolStore()
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
            capabilities = ["embedding"] if profile.kind == "embedding" else ["completion"]
            if "image" in profile.capabilities.input_modalities:
                capabilities.append("multimodal")
            result.append(
                {
                    "model_id": profile.served_model_name,
                    "kind": profile.kind,
                    "format": artifact.model_format,
                    "context_length": profile.limits.max_input_tokens,
                    "parameter_count": None,
                    "size_bytes": size_bytes,
                    "embedding_dimensions": profile.embedding_dimensions,
                    "capabilities": capabilities,
                    "phase": str(runtime.get("phase") or "idle"),
                }
            )
        return {"models": result}

    @app.post("/runtimes/load")
    async def load_runtime(request: InferenceNodeAction) -> dict[str, Any]:
        profile = _resolve_profile(request)
        return {"runtime": _runtime_payload(await runtime_manager.load(profile.profile_id))}

    @app.post("/runtimes/unload")
    async def unload_runtime(request: InferenceNodeAction) -> dict[str, Any]:
        profile = _resolve_profile(request)
        return {"runtime": _runtime_payload(await runtime_manager.unload(profile.profile_id), profile=profile)}

    @app.post("/runtimes/restart")
    async def restart_runtime(request: InferenceNodeAction) -> dict[str, Any]:
        profile = _resolve_profile(request)
        return {"runtime": _runtime_payload(await runtime_manager.restart(profile.profile_id))}

    return app


def _resolve_profile(request: InferenceNodeAction) -> ModelPoolProfile:
    profiles = [
        profile
        for profile in ModelPoolStore().list_profiles(kind=request.kind, enabled=True)
        if profile.served_model_name == request.model_id
    ]
    if len(profiles) != 1:
        raise HTTPException(
            status_code=404,
            detail=f"enabled {request.kind} model is not registered on the inference node: {request.model_id}",
        )
    return profiles[0]


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
