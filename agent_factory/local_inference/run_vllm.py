from __future__ import annotations

import argparse
import os
from pathlib import Path

from agent_factory.local_inference.launcher import VllmLaunchConfig, build_vllm_command
from agent_factory.local_inference.rocm import inspect_rocm_runtime
from agent_factory.local_inference.tool_calling import resolve_vllm_tool_call_parser
from agent_factory.model_pool.store import ModelPoolStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Load a registered local chat model with vLLM on AMD ROCm")
    parser.add_argument("--profile-id")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()

    inspect_rocm_runtime(require_available=True)
    store = ModelPoolStore()
    profile_id = args.profile_id or store.resolve_default_profile_id("main")
    if not profile_id:
        raise ValueError("no enabled default chat profile is configured in the local model pool")
    profile = store.require_profile(profile_id)
    if profile.kind != "chat" or profile.engine != "vllm_rocm":
        raise ValueError(f"profile {profile_id} is not a local vLLM chat profile")
    if not profile.enabled:
        raise ValueError(f"local chat profile is disabled: {profile.profile_id}")
    artifact = store.require_artifact(profile.artifact_id)
    if not artifact.enabled:
        raise ValueError(f"local chat artifact is disabled: {artifact.artifact_id}")

    model_path = artifact.resolved_path()
    command = build_vllm_command(
        VllmLaunchConfig(
            model_path=model_path,
            tokenizer_path=(
                None
                if not artifact.tokenizer_path
                else Path(artifact.tokenizer_path).expanduser().resolve()
            ),
            served_model_name=profile.served_model_name,
            host=args.host,
            port=args.port,
            dtype=profile.inference.dtype,
            tensor_parallel_size=profile.inference.tensor_parallel_size,
            max_model_len=profile.limits.max_input_tokens,
            quantization=profile.inference.quantization,
            gpu_memory_utilization=profile.inference.gpu_memory_utilization,
            trust_remote_code=profile.inference.trust_remote_code,
            tool_call_parser=resolve_vllm_tool_call_parser(
                model_path,
                tool_calling_enabled=profile.capabilities.tool_calling,
            ),
        )
    )
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
