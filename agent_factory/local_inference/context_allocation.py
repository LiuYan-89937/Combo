from __future__ import annotations

from dataclasses import dataclass

from agent_factory.model_pool.schema import LlamaCppInferenceConfig, ModelPoolLimits


@dataclass(frozen=True, slots=True)
class LlamaContextAllocation:
    per_slot_tokens: int
    parallel_slots: int
    server_context_tokens: int


def resolve_llama_context_allocation(
    limits: ModelPoolLimits,
    inference: LlamaCppInferenceConfig,
) -> LlamaContextAllocation | None:
    per_slot_tokens = limits.max_input_tokens
    if per_slot_tokens is None:
        return None
    parallel_slots = inference.parallel_slots
    return LlamaContextAllocation(
        per_slot_tokens=per_slot_tokens,
        parallel_slots=parallel_slots,
        server_context_tokens=per_slot_tokens * parallel_slots,
    )
