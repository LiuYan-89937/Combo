from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.types import PolicyDecision


class PolicyEngine:
    def evaluate_precheck(
        self,
        *,
        state: RuntimeState,
        binding: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        binding = binding or {}
        rules = dict(binding.get("rules") or {})
        user_input = (state.conversation.current_user_input or "").lower()
        blocked_phrases = [str(item).lower() for item in rules.get("blocked_phrases", [])]
        approval_phrases = [str(item).lower() for item in rules.get("approval_phrases", [])]
        for phrase in blocked_phrases:
            if phrase and phrase in user_input:
                return PolicyDecision(status="blocked", reason=f"Blocked by phrase: {phrase}")
        for phrase in approval_phrases:
            if phrase and phrase in user_input:
                return PolicyDecision(
                    status="interrupted",
                    reason=f"Approval required for phrase: {phrase}",
                    approval_required=True,
                    interrupt_required=True,
                    interrupt_type="approval_required",
                )
        return PolicyDecision(status="allowed")

    def evaluate_postcheck(
        self,
        *,
        state: RuntimeState,
        binding: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        binding = binding or {}
        rules = dict(binding.get("rules") or {})
        answer = (state.conversation.final_answer or state.conversation.assistant_draft or "").lower()
        refusal_phrases = [str(item).lower() for item in rules.get("refusal_phrases", [])]
        for phrase in refusal_phrases:
            if phrase and phrase in answer:
                return PolicyDecision(status="blocked", reason=f"Refusal phrase matched: {phrase}")
        return PolicyDecision(status="allowed")
