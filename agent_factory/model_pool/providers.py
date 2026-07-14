from __future__ import annotations

from typing import Any


def list_local_inference_engines() -> list[dict[str, Any]]:
    return [
        {
            "engine": "vllm_rocm",
            "display_name": "vLLM on AMD ROCm",
            "kind": "chat",
            "transport": "local_vllm",
        },
        {
            "engine": "transformers_rocm",
            "display_name": "Transformers on AMD ROCm",
            "kind": "embedding",
            "transport": "in_process",
        },
    ]
