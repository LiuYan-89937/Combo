from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from combo.runtime_protocol.contracts import ExecutionStrategy, WorkspaceMode


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    strategy: ExecutionStrategy
    agent_name: str
    system_prompt: str
    objective: str
    capability_names: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    isolation: WorkspaceMode = "shared"


@dataclass(frozen=True, slots=True)
class DelegationContinuationRequest:
    agent_name: str
    instruction: str
    acceptance_criteria: tuple[str, ...]
    objective: str | None = None
    created_at: str | None = None


@dataclass(frozen=True, slots=True)
class DelegationMessageRequest:
    agent_name: str
    message: str
    objective: str | None = None
    created_at: str | None = None


def normalize_isolation(value: Any) -> WorkspaceMode:
    """把 isolation 参数归一化为 ``shared`` 或 ``worktree``。"""
    isolation = str(value or "").strip().lower() or "shared"
    if isolation == "shared":
        return "shared"
    if isolation == "worktree":
        return "worktree"
    raise ValueError("isolation must be shared or worktree")
