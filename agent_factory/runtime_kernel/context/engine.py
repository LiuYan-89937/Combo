from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.state import RuntimeState


class ContextEngine:
    def build_model_context(
        self,
        *,
        state: RuntimeState,
        binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        binding = binding or {}
        variables = binding.get("variables") or []
        context = {
            "current_user_input": state.conversation.current_user_input,
            "summary_memory": state.memory.summary_memory,
            "retrieved_items": state.knowledge.ranked_items or state.knowledge.retrieved_items,
            "policy": {
                "risk_level": state.policy.risk_level,
                "blocked": state.policy.blocked,
            },
        }
        if variables:
            filtered = {}
            for key in variables:
                if key == "conversation":
                    filtered["conversation"] = {
                        "current_user_input": state.conversation.current_user_input,
                        "turn_index": state.conversation.turn_index,
                    }
                elif key == "context":
                    filtered["context"] = state.context.model_context
                elif key == "memory":
                    filtered["memory"] = {
                        "summary_memory": state.memory.summary_memory,
                        "recall_items": state.memory.recall_items,
                    }
                elif key == "knowledge":
                    filtered["knowledge"] = {
                        "retrieved_items": state.knowledge.ranked_items or state.knowledge.retrieved_items,
                        "citations": state.knowledge.citations,
                    }
                else:
                    filtered[key] = context.get(key)
            return filtered
        return context

    def build_tool_context(
        self,
        *,
        state: RuntimeState,
        binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "current_user_input": state.conversation.current_user_input,
            "memory": {
                "recall_items": state.memory.recall_items,
            },
            "knowledge": {
                "retrieved_items": state.knowledge.ranked_items or state.knowledge.retrieved_items,
            },
            "policy": {
                "risk_level": state.policy.risk_level,
            },
        }
