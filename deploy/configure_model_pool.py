from __future__ import annotations

import argparse
from pathlib import Path

from agent_factory.model_pool.schema import (
    ExternalInferenceConfig,
    LlamaCppInferenceConfig,
    LocalModelArtifact,
    ModelPoolCapabilities,
    ModelPoolLimits,
    ModelPoolProfile,
    TransformersInferenceConfig,
)
from agent_factory.model_pool.store import ModelPoolStore


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.mode == "node" and (args.chat_model_path is None or args.embedding_model_path is None):
        parser.error("node mode requires --chat-model-path and --embedding-model-path")
    store = ModelPoolStore(path=args.store_path)
    chat_inference = LlamaCppInferenceConfig(
        gpu_layers=args.gpu_layers,
        parallel_slots=args.parallel_slots,
        cache_type_k=args.cache_type_k,
        cache_type_v=args.cache_type_v,
        flash_attention=args.flash_attention,
        mmproj_path=str(args.chat_mmproj_path) if args.chat_mmproj_path else None,
    )
    embedding_inference = TransformersInferenceConfig(
        trust_remote_code=args.embedding_trust_remote_code,
    )

    if args.mode == "node":
        chat_artifact = LocalModelArtifact(
            artifact_id=args.chat_artifact_id,
            display_name=args.chat_served_model_name,
            kind="chat",
            source="local_storage",
            local_path=str(args.chat_model_path),
            model_format="llama_cpp",
            revision=args.chat_revision,
            checksum=args.chat_checksum,
        )
        embedding_artifact = LocalModelArtifact(
            artifact_id=args.embedding_artifact_id,
            display_name=args.embedding_served_model_name,
            kind="embedding",
            source="local_storage",
            local_path=str(args.embedding_model_path),
            model_format="transformers",
            revision=args.embedding_revision,
        )
        chat_engine = "llama_cpp_rocm"
        embedding_engine = "transformers_rocm"
        chat_profile_inference = chat_inference
        embedding_profile_inference = embedding_inference
    else:
        chat_artifact = LocalModelArtifact(
            artifact_id=args.chat_artifact_id,
            display_name=args.chat_served_model_name,
            kind="chat",
            source="external_endpoint",
            external_model_id=args.chat_served_model_name,
            model_format="llama_cpp",
            revision=args.chat_revision,
            checksum=args.chat_checksum,
        )
        embedding_artifact = LocalModelArtifact(
            artifact_id=args.embedding_artifact_id,
            display_name=args.embedding_served_model_name,
            kind="embedding",
            source="external_endpoint",
            external_model_id=args.embedding_served_model_name,
            model_format="transformers",
            revision=args.embedding_revision,
        )
        chat_engine = "external"
        embedding_engine = "external"
        chat_profile_inference = ExternalInferenceConfig(remote_inference=chat_inference)
        embedding_profile_inference = ExternalInferenceConfig(remote_inference=embedding_inference)

    store.upsert_artifact(chat_artifact)
    store.upsert_artifact(embedding_artifact)
    chat_profile = store.upsert_profile(
        ModelPoolProfile(
            profile_id=args.chat_profile_id,
            display_name=args.chat_served_model_name,
            kind="chat",
            artifact_id=chat_artifact.artifact_id,
            engine=chat_engine,
            served_model_name=args.chat_served_model_name,
            capabilities=ModelPoolCapabilities(
                input_modalities=["text", "image"] if args.chat_mmproj_path else ["text"],
                output_modalities=["text"],
                tool_calling=True,
                structured_output_methods=["function_calling", "json_mode"],
                reasoning_supported=args.reasoning_supported,
                reasoning_content=args.reasoning_supported,
            ),
            limits=ModelPoolLimits(
                max_input_tokens=args.context_size,
                max_output_tokens=args.max_output_tokens,
                context_compression_threshold_tokens=args.compression_threshold,
            ),
            inference=chat_profile_inference,
        )
    )
    embedding_profile = store.upsert_profile(
        ModelPoolProfile(
            profile_id=args.embedding_profile_id,
            display_name=args.embedding_served_model_name,
            kind="embedding",
            artifact_id=embedding_artifact.artifact_id,
            engine=embedding_engine,
            served_model_name=args.embedding_served_model_name,
            capabilities=ModelPoolCapabilities(
                input_modalities=["text"],
                output_modalities=["text"],
                tool_calling=False,
                structured_output_methods=[],
            ),
            limits=ModelPoolLimits(),
            inference=embedding_profile_inference,
            embedding_dimensions=args.embedding_dimensions,
            normalize_embeddings=True,
        )
    )
    store.disable_other_profiles("chat", chat_profile.profile_id)
    store.disable_other_profiles("embedding", embedding_profile.profile_id)
    for role in ("main", "task", "compression"):
        store.set_default_profile_id(role, chat_profile.profile_id)
    store.set_default_profile_id("embedding", embedding_profile.profile_id)
    store.set_active_profile_id("chat", chat_profile.profile_id)
    store.set_active_profile_id("embedding", embedding_profile.profile_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create deterministic chat and embedding profiles")
    parser.add_argument("--mode", choices=("node", "client"), required=True)
    parser.add_argument("--store-path", type=Path, required=True)
    parser.add_argument("--chat-artifact-id", default="qwen3_6_35b_a3b_apex_i_quality_gguf")
    parser.add_argument("--chat-profile-id", required=True)
    parser.add_argument("--chat-served-model-name", required=True)
    parser.add_argument("--chat-model-path", type=Path)
    parser.add_argument("--chat-mmproj-path", type=Path)
    parser.add_argument("--chat-revision", default="")
    parser.add_argument("--chat-checksum", default="")
    parser.add_argument("--context-size", type=int, required=True)
    parser.add_argument("--max-output-tokens", type=int, required=True)
    parser.add_argument("--compression-threshold", type=int, required=True)
    parser.add_argument("--gpu-layers", type=int, required=True)
    parser.add_argument("--parallel-slots", type=int, required=True)
    parser.add_argument("--cache-type-k", required=True)
    parser.add_argument("--cache-type-v", required=True)
    parser.add_argument("--flash-attention", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--reasoning-supported",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--embedding-artifact-id", default="bge_m3_transformers")
    parser.add_argument("--embedding-profile-id", required=True)
    parser.add_argument("--embedding-served-model-name", required=True)
    parser.add_argument("--embedding-model-path", type=Path)
    parser.add_argument("--embedding-revision", default="")
    parser.add_argument("--embedding-dimensions", type=int, required=True)
    parser.add_argument(
        "--embedding-trust-remote-code",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    return parser


if __name__ == "__main__":
    main()
