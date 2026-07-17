from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from agent_factory.local_inference.config import load_inference_telemetry_endpoint
from agent_factory.local_inference.http_client import create_private_async_http_client
from agent_factory.local_inference.implementation import LlamaImplementationStatus
from agent_factory.model_pool.schema import (
    ExternalInferenceConfig,
    LlamaCppInferenceConfig,
    ModelPoolCapabilities,
    ModelPoolLimits,
    ModelPoolProfile,
    StableDiffusionCppInferenceConfig,
    TransformersInferenceConfig,
)


RuntimeKind = Literal["chat", "embedding", "image_generation"]
RuntimeAction = Literal["load", "unload", "restart"]


class InferenceNodeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RuntimeKind
    model_id: str
    profile: "InferenceNodeProfileConfiguration | None" = None


class InferenceNodeProfileConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limits: ModelPoolLimits
    capabilities: ModelPoolCapabilities
    inference: LlamaCppInferenceConfig | TransformersInferenceConfig | StableDiffusionCppInferenceConfig | None = None
    embedding_dimensions: int | None = None
    normalize_embeddings: bool = True

    @classmethod
    def from_profile(cls, profile: ModelPoolProfile) -> "InferenceNodeProfileConfiguration":
        inference = profile.inference
        remote_inference = (
            inference.remote_inference
            if isinstance(inference, ExternalInferenceConfig)
            else inference
        )
        return cls(
            limits=profile.limits,
            capabilities=profile.capabilities,
            inference=remote_inference,
            embedding_dimensions=profile.embedding_dimensions,
            normalize_embeddings=profile.normalize_embeddings,
        )


class InferenceMemoryEstimateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RuntimeKind
    model_id: str
    profile: InferenceNodeProfileConfiguration


class InferenceNodeClient:
    async def software(self) -> dict[str, Any]:
        endpoint = load_inference_telemetry_endpoint()
        async with create_private_async_http_client(endpoint) as client:
            response = await client.get(endpoint.endpoint("/runtime/software"))
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("inference node response does not contain software metadata")
        return payload

    async def llama_implementation(self) -> LlamaImplementationStatus:
        endpoint = load_inference_telemetry_endpoint()
        async with create_private_async_http_client(endpoint) as client:
            response = await client.get(endpoint.endpoint("/runtime/llama"))
            if response.status_code == 404:
                response = await client.get(endpoint.endpoint("/runtime/software"))
                response.raise_for_status()
                software = response.json()
                payload = software.get("llama_implementation") if isinstance(software, dict) else None
            else:
                response.raise_for_status()
                payload = response.json()
        if not isinstance(payload, dict):
            return LlamaImplementationStatus(
                error="inference node does not report llama.cpp implementation metadata",
            )
        return LlamaImplementationStatus.model_validate(payload)

    async def runtimes(self) -> list[dict[str, Any]]:
        endpoint = load_inference_telemetry_endpoint()
        async with create_private_async_http_client(endpoint) as client:
            response = await client.get(endpoint.endpoint("/runtimes"))
            response.raise_for_status()
            payload = response.json()
        runtimes = payload.get("runtimes") if isinstance(payload, dict) else None
        if not isinstance(runtimes, list):
            raise ValueError("inference node response does not contain runtimes")
        return [item for item in runtimes if isinstance(item, dict)]

    async def action(
        self,
        action: RuntimeAction,
        *,
        kind: RuntimeKind,
        model_id: str,
        profile: ModelPoolProfile | None = None,
    ) -> dict[str, Any]:
        endpoint = load_inference_telemetry_endpoint()
        request = InferenceNodeAction(
            kind=kind,
            model_id=model_id,
            profile=InferenceNodeProfileConfiguration.from_profile(profile) if profile else None,
        )
        async with create_private_async_http_client(endpoint) as client:
            response = await client.post(
                endpoint.endpoint(f"/runtimes/{action}"),
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
            payload = response.json()
        runtime = payload.get("runtime") if isinstance(payload, dict) else None
        if not isinstance(runtime, dict):
            raise ValueError("inference node response does not contain a runtime")
        return runtime

    async def memory_estimate(
        self,
        request: InferenceMemoryEstimateRequest,
    ) -> dict[str, Any]:
        endpoint = load_inference_telemetry_endpoint()
        async with create_private_async_http_client(endpoint) as client:
            response = await client.post(
                endpoint.endpoint("/models/memory-estimate"),
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
            payload = response.json()
        estimate = payload.get("estimate") if isinstance(payload, dict) else None
        if not isinstance(estimate, dict):
            raise ValueError("inference node response does not contain a memory estimate")
        return estimate
