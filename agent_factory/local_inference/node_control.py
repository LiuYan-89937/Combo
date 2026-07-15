from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from agent_factory.local_inference.config import load_inference_telemetry_endpoint
from agent_factory.local_inference.http_client import create_private_async_http_client


RuntimeKind = Literal["chat", "embedding"]
RuntimeAction = Literal["load", "unload", "restart"]


class InferenceNodeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RuntimeKind
    model_id: str


class InferenceNodeClient:
    async def runtimes(self) -> list[dict[str, Any]]:
        endpoint = load_inference_telemetry_endpoint(timeout_seconds=5.0)
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
    ) -> dict[str, Any]:
        endpoint = load_inference_telemetry_endpoint(timeout_seconds=10.0)
        request = InferenceNodeAction(kind=kind, model_id=model_id)
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
