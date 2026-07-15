from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_factory.local_inference.node_control import InferenceNodeProfileConfiguration
from agent_factory.local_inference.rocm import RocmDeviceInfo
from agent_factory.model_pool.schema import (
    LlamaCppInferenceConfig,
    LocalModelArtifact,
    ModelPoolProfile,
)


_ELEMENT_BYTES = {
    "f16": 2.0,
    "bf16": 2.0,
    "q8_0": 34.0 / 32.0,
    "q4_0": 18.0 / 32.0,
}


@dataclass(frozen=True, slots=True)
class InferenceMemoryEstimate:
    available: bool
    model_id: str
    context_tokens: int | None
    parallel_slots: int
    cache_type_k: str
    cache_type_v: str
    model_allocation_bytes: int | None
    kv_cache_bytes: int | None
    current_used_bytes: int | None
    projected_used_bytes: int | None
    total_memory_bytes: int | None
    remaining_memory_bytes: int | None
    utilization_percent: float | None
    fits: bool | None
    basis: str
    error: str = ""

    def payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _GgufAttentionMetadata:
    block_count: int
    kv_block_count: int
    head_count_kv: int
    key_length: int
    value_length: int


def estimate_inference_memory(
    *,
    profile: ModelPoolProfile,
    artifact: LocalModelArtifact,
    requested: InferenceNodeProfileConfiguration,
    runtime: dict[str, Any] | None,
    device: RocmDeviceInfo | None,
) -> InferenceMemoryEstimate:
    requested_inference = requested.inference
    if profile.kind != "chat" or not isinstance(requested_inference, LlamaCppInferenceConfig):
        return _unavailable(profile.served_model_name, "memory estimation requires a llama.cpp chat profile")
    if device is None or device.total_memory_bytes <= 0:
        return _unavailable(profile.served_model_name, "ROCm VRAM telemetry is unavailable")
    context_tokens = requested.limits.max_input_tokens
    if context_tokens is None:
        return _unavailable(profile.served_model_name, "context length is required for memory estimation")

    try:
        metadata = _read_attention_metadata(artifact.resolved_path())
        requested_kv = _kv_cache_bytes(metadata, context_tokens, requested_inference)
        model_allocation = _model_allocation_bytes(artifact, profile)
        current_used = device.used_memory_bytes
        projected_used, basis = _projected_used_bytes(
            current_used=current_used,
            model_allocation=model_allocation,
            requested_kv=requested_kv,
            profile=profile,
            runtime=runtime,
            metadata=metadata,
        )
    except (ImportError, OSError, ValueError) as exc:
        return _unavailable(profile.served_model_name, f"{type(exc).__name__}: {exc}")

    remaining = max(0, device.total_memory_bytes - projected_used) if projected_used is not None else None
    utilization = (
        projected_used / device.total_memory_bytes * 100.0
        if projected_used is not None
        else None
    )
    return InferenceMemoryEstimate(
        available=True,
        model_id=profile.served_model_name,
        context_tokens=context_tokens,
        parallel_slots=requested_inference.parallel_slots,
        cache_type_k=requested_inference.cache_type_k,
        cache_type_v=requested_inference.cache_type_v,
        model_allocation_bytes=model_allocation,
        kv_cache_bytes=requested_kv,
        current_used_bytes=current_used,
        projected_used_bytes=projected_used,
        total_memory_bytes=device.total_memory_bytes,
        remaining_memory_bytes=remaining,
        utilization_percent=utilization,
        fits=projected_used <= device.total_memory_bytes if projected_used is not None else None,
        basis=basis,
    )


def _read_attention_metadata(path: Path) -> _GgufAttentionMetadata:
    try:
        from gguf import GGUFReader
    except ImportError as exc:
        raise ImportError("the gguf package is required to inspect model metadata") from exc

    reader = GGUFReader(str(path))
    architecture = str(_field_value(reader, "general.architecture"))
    if not architecture:
        raise ValueError("GGUF metadata does not define general.architecture")
    prefix = f"{architecture}."
    block_count = _positive_int(_field_value(reader, prefix + "block_count"), "block_count")
    interval = _optional_positive_int(_field_value(reader, prefix + "full_attention_interval"))
    kv_block_count = max(1, block_count // interval) if interval else block_count
    head_count = _positive_int(_field_value(reader, prefix + "attention.head_count"), "head_count")
    head_count_kv = _positive_int(
        _field_value(reader, prefix + "attention.head_count_kv") or head_count,
        "head_count_kv",
    )
    embedding_length = _positive_int(
        _field_value(reader, prefix + "embedding_length"),
        "embedding_length",
    )
    default_head_length = embedding_length // head_count
    key_length = _positive_int(
        _field_value(reader, prefix + "attention.key_length") or default_head_length,
        "key_length",
    )
    value_length = _positive_int(
        _field_value(reader, prefix + "attention.value_length") or default_head_length,
        "value_length",
    )
    return _GgufAttentionMetadata(
        block_count=block_count,
        kv_block_count=kv_block_count,
        head_count_kv=head_count_kv,
        key_length=key_length,
        value_length=value_length,
    )


def _field_value(reader: Any, key: str) -> Any:
    field = reader.fields.get(key)
    if field is None:
        return None
    values = field.contents()
    if isinstance(values, list) and len(values) == 1:
        return values[0]
    return values


def _positive_int(value: Any, name: str) -> int:
    number = int(value or 0)
    if number <= 0:
        raise ValueError(f"GGUF metadata does not define a valid {name}")
    return number


def _optional_positive_int(value: Any) -> int | None:
    number = int(value or 0)
    return number if number > 0 else None


def _kv_cache_bytes(
    metadata: _GgufAttentionMetadata,
    context_tokens: int,
    inference: LlamaCppInferenceConfig,
) -> int:
    key_bytes = _ELEMENT_BYTES[inference.cache_type_k]
    value_bytes = _ELEMENT_BYTES[inference.cache_type_v]
    elements_per_token = metadata.kv_block_count * metadata.head_count_kv
    bytes_per_token = elements_per_token * (
        metadata.key_length * key_bytes + metadata.value_length * value_bytes
    )
    return int(bytes_per_token * context_tokens * inference.parallel_slots)


def _model_allocation_bytes(artifact: LocalModelArtifact, profile: ModelPoolProfile) -> int:
    total = artifact.resolved_path().stat().st_size
    inference = profile.inference
    if isinstance(inference, LlamaCppInferenceConfig) and inference.mmproj_path:
        projector = Path(inference.mmproj_path).expanduser().resolve()
        if projector.is_file():
            total += projector.stat().st_size
    return total


def _projected_used_bytes(
    *,
    current_used: int | None,
    model_allocation: int,
    requested_kv: int,
    profile: ModelPoolProfile,
    runtime: dict[str, Any] | None,
    metadata: _GgufAttentionMetadata,
) -> tuple[int | None, str]:
    if current_used is None:
        return None, "model_and_kv_only"
    runtime_ready = (
        isinstance(runtime, dict)
        and str(runtime.get("phase") or "") == "ready"
        and str(runtime.get("profile_id") or "") == profile.profile_id
    )
    current_inference = profile.inference
    current_context = profile.limits.max_input_tokens
    if runtime_ready and isinstance(current_inference, LlamaCppInferenceConfig) and current_context:
        current_kv = _kv_cache_bytes(metadata, current_context, current_inference)
        return max(0, current_used - current_kv) + requested_kv, "live_runtime_adjusted"
    return current_used + model_allocation + requested_kv, "unloaded_conservative"


def _unavailable(model_id: str, error: str) -> InferenceMemoryEstimate:
    return InferenceMemoryEstimate(
        available=False,
        model_id=model_id,
        context_tokens=None,
        parallel_slots=1,
        cache_type_k="",
        cache_type_v="",
        model_allocation_bytes=None,
        kv_cache_bytes=None,
        current_used_bytes=None,
        projected_used_bytes=None,
        total_memory_bytes=None,
        remaining_memory_bytes=None,
        utilization_percent=None,
        fits=None,
        basis="unavailable",
        error=error,
    )
