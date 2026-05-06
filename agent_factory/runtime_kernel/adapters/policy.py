from __future__ import annotations

from typing import Any, Protocol

from agent_factory.runtime_kernel.types import PolicyDecision


class PolicyEngineAdapter(Protocol):
    def evaluate_precheck(
        self,
        *,
        state: Any,
        binding: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        ...
