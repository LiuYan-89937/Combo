from __future__ import annotations

from typing import Any

from agent_factory.tooling.builtins.filesystem.common import path_risk_result
from agent_factory.tooling.builtins.filesystem.workspace_transaction import (
    commit_transaction,
    preview_transaction,
)
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action == "commit":
        return ToolRiskResult(
            action="ask",
            risk_level="medium",
            reasons=["committing a workspace transaction can create, modify, move, copy, or delete files"],
            facts={"transaction_id": str(arguments.get("transaction_id") or "")},
        ).model_dump(mode="json")
    operations = arguments.get("operations")
    if not isinstance(operations, list) or not operations:
        return ToolRiskResult(
            action="deny",
            risk_level="high",
            reasons=["preview requires a non-empty operations array"],
        ).model_dump(mode="json")
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        for key in ("path", "source_path", "destination_path"):
            if key not in operation:
                continue
            result = ToolRiskResult.model_validate(
                path_risk_result(
                    {key: operation[key]},
                    context,
                    path_key=key,
                    default_action="ask",
                    sensitive_action="ask",
                )
            )
            if result.action == "deny":
                return result.model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["preview validates and stages a transaction plan without changing workspace files"],
    ).model_dump(mode="json")


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action == "preview":
        operations = arguments.get("operations")
        if not isinstance(operations, list) or not operations:
            raise ValueError("operations must be a non-empty array")
        return tool_envelope(preview_transaction(operations, resources))
    if action == "commit":
        transaction_id = str(arguments.get("transaction_id") or "").strip()
        if not transaction_id:
            raise ValueError("transaction_id is required for commit")
        return tool_envelope(commit_transaction(transaction_id, resources))
    raise ValueError("action must be preview or commit")
