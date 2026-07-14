from __future__ import annotations

import argparse
import os
from pathlib import Path

from agent_factory.local_inference.launcher import VllmLaunchConfig, build_vllm_command
from agent_factory.local_inference.rocm import inspect_rocm_runtime
from agent_factory.model_pool.store import ModelPoolStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Load a registered local chat model with vLLM on AMD ROCm")
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()

    inspect_rocm_runtime(require_available=True)
    store = ModelPoolStore(setup=False)
    profile = store.require_profile(args.profile_id)
    if profile.kind != "chat" or profile.engine != "vllm_rocm":
        raise ValueError(f"profile {args.profile_id} is not a local vLLM chat profile")
    if not profile.enabled:
        raise ValueError(f"local chat profile is disabled: {profile.profile_id}")
    artifact = store.require_artifact(profile.artifact_id)
    if not artifact.enabled:
        raise ValueError(f"local chat artifact is disabled: {artifact.artifact_id}")

    command = build_vllm_command(
        VllmLaunchConfig(
            model_path=artifact.resolved_path(),
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
        )
    )
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
