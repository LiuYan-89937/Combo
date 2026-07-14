from __future__ import annotations

from typing import Any

from agent_factory.model_pool.schema import (
    SUPPORTED_LOCAL_DTYPES,
    SUPPORTED_VLLM_QUANTIZATIONS,
)


def list_local_inference_engines() -> list[dict[str, Any]]:
    return [
        {
            "engine": "vllm_rocm",
            "display_name": "vLLM on AMD ROCm",
            "kind": "chat",
            "transport": "local_vllm",
            "parameters": {
                "dtype": {"default": "auto", "options": list(SUPPORTED_LOCAL_DTYPES)},
                "quantization": {
                    "default": None,
                    "options": list(SUPPORTED_VLLM_QUANTIZATIONS),
                },
                "gpu_memory_percent": {"default": 80, "min": 50, "max": 95, "step": 5},
            },
        },
        {
            "engine": "transformers_rocm",
            "display_name": "Transformers on AMD ROCm",
            "kind": "embedding",
            "transport": "in_process",
            "parameters": {
                "dtype": {"default": "auto", "options": ["auto"]},
                "quantization": {"default": None, "options": []},
                "gpu_memory_percent": None,
            },
        },
    ]
