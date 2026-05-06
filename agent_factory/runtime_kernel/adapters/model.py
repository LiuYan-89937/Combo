from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from agent_factory.runtime_kernel.types import ModelInvocationResult


class ModelServiceAdapter(Protocol):
    def generate(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
    ) -> ModelInvocationResult:
        ...


class ScriptedModelService:
    def __init__(self, responses: Sequence[ModelInvocationResult] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
    ) -> ModelInvocationResult:
        self.calls.append({"state": state, "prompt_binding": prompt_binding or {}})
        if self._responses:
            return self._responses.pop(0)
        current_input = getattr(getattr(state, "conversation", None), "current_user_input", None)
        text = str(current_input or "")
        prompt_id = str((prompt_binding or {}).get("prompt_id") or "")
        if "clarify" in prompt_id and len(text.strip()) < 12:
            return ModelInvocationResult(
                assistant_draft="我需要更多信息来继续。",
                clarification_question="请补充你的目标或使用场景。",
                requests_tool=False,
                route_decision="subgraph.need_more_input",
            )
        return ModelInvocationResult(
            assistant_draft=f"Echo: {text}",
            final_answer=f"Echo: {text}",
            requests_tool=False,
        )
