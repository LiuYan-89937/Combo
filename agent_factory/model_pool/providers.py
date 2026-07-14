from __future__ import annotations

from typing import Any



def list_local_inference_engines() -> list[dict[str, Any]]:
    return [
        {
            "engine": "llama_cpp_rocm",
            "display_name": "llama.cpp on AMD ROCm",
            "kind": "chat",
            "transport": "local_llama_cpp",
            "parameters": {
                "gpu_layers": {"default": 99, "min": 0},
                "parallel_slots": {"default": 1, "min": 1},
                "cache_types": ["f16", "bf16", "q8_0", "q4_0"],
            },
        },
        {
            "engine": "transformers_rocm",
            "display_name": "Transformers on AMD ROCm",
            "kind": "embedding",
            "transport": "in_process",
            "parameters": {},
        },
    ]
