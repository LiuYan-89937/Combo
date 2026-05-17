from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable, Literal, Mapping

from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.tooling.schema_compiler import CompiledJsonSchema
from agent_factory.tooling.spec import ToolObservation, ToolSpec


ToolApprovalAction = Literal["approve", "deny", "revise"]
ToolApprovalHandler = Callable[[ToolSpec, dict[str, Any]], "ToolApprovalDecision"]
TRUST_TOOL_ACTIONS = {"trust", "trust_tool", "always_allow", "no_approval", "无需审批"}


class ToolApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ToolApprovalAction
    revision_guidance: str = ""


class ToolApprovalTrustStore:
    def __init__(self) -> None:
        self._trusted_tool_ids: set[str] = set()

    def trust_tool(self, tool_id: str) -> None:
        self._trusted_tool_ids.add(tool_id)

    def is_trusted(self, tool_id: str) -> bool:
        return tool_id in self._trusted_tool_ids


DEFAULT_TOOL_APPROVAL_TRUST_STORE = ToolApprovalTrustStore()


@dataclass(slots=True)
class ToolExecutionGateway:
    spec: ToolSpec
    input_schema: CompiledJsonSchema
    output_schema: CompiledJsonSchema
    entrypoint: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    global_resources: Mapping[str, Any]
    approval_handler: ToolApprovalHandler | None = None
    max_revisions: int = 5

    def execute(
        self,
        arguments: dict[str, Any],
        *,
        tool_call_id: str | None = None,
        revision_count: int = 0,
    ) -> dict[str, Any]:
        if revision_count >= self.max_revisions:
            return self._observation(
                "execution_failed",
                f"Tool revision limit exceeded: {self.max_revisions}",
                tool_call_id=tool_call_id,
                arguments=arguments,
                retryable=False,
                errors=[f"max revisions exceeded: {self.max_revisions}"],
            )
        input_errors = self.input_schema.errors_for(arguments)
        if input_errors:
            return self._observation(
                "invalid_arguments",
                "Tool arguments failed schema validation.",
                tool_call_id=tool_call_id,
                arguments=arguments,
                errors=input_errors,
            )
        approval = self._approval(arguments)
        if approval.action == "deny":
            return self._observation(
                "denied",
                "Human denied this tool call.",
                tool_call_id=tool_call_id,
                arguments=arguments,
                user_instruction=approval.revision_guidance or None,
            )
        if approval.action == "revise":
            return self._observation(
                "revision_requested",
                "Human requested argument revision before execution.",
                tool_call_id=tool_call_id,
                arguments=arguments,
                user_instruction=approval.revision_guidance or "Please regenerate the tool call.",
            )
        try:
            tool_resources = self._resolve_resources()
            output = self.entrypoint(arguments=arguments, resources=tool_resources)
        except Exception as exc:
            return self._observation(
                "execution_failed",
                f"Tool execution failed: {type(exc).__name__}: {exc}",
                tool_call_id=tool_call_id,
                arguments=arguments,
                errors=[f"{type(exc).__name__}: {exc}"],
            )
        if not isinstance(output, dict):
            return self._observation(
                "invalid_output",
                "Tool entrypoint must return a dict.",
                tool_call_id=tool_call_id,
                arguments=arguments,
                output={"value": output},
                errors=["output is not a dict"],
            )
        output_errors = self.output_schema.errors_for(output)
        if output_errors:
            return self._observation(
                "invalid_output",
                "Tool output failed schema validation.",
                tool_call_id=tool_call_id,
                arguments=arguments,
                output=output,
                errors=output_errors,
            )
        return self._observation(
            "completed",
            "Tool execution completed.",
            tool_call_id=tool_call_id,
            arguments=arguments,
            output=output,
            retryable=False,
        )

    def _approval(self, arguments: dict[str, Any]) -> ToolApprovalDecision:
        if not self.spec.approval_required:
            return ToolApprovalDecision(action="approve")
        handler = self.approval_handler or default_interrupt_approval
        return handler(self.spec, arguments)

    def _resolve_resources(self) -> dict[str, Any]:
        resources: dict[str, Any] = {}
        missing: list[str] = []
        for local_name, global_key in self.spec.resources.items():
            if global_key not in self.global_resources:
                missing.append(global_key)
                continue
            resources[local_name] = self.global_resources[global_key]
        if missing:
            raise KeyError(f"missing required resources: {', '.join(sorted(missing))}")
        return resources

    def _observation(
        self,
        status,
        message: str,
        *,
        tool_call_id: str | None,
        arguments: dict[str, Any],
        user_instruction: str | None = None,
        retryable: bool = True,
        output: dict[str, Any] | None = None,
        errors: list[str] | None = None,
    ) -> dict[str, Any]:
        return ToolObservation(
            status=status,
            tool_id=self.spec.id,
            tool_call_id=tool_call_id,
            message=message,
            user_instruction=user_instruction,
            retryable=retryable,
            arguments=arguments,
            output=output,
            errors=errors or [],
        ).model_dump(mode="json")


def default_tool_max_revisions() -> int:
    raw = os.getenv("AGENTFACTORY_TOOL_MAX_REVISIONS", "5").strip()
    try:
        value = int(raw)
    except ValueError:
        return 5
    return max(value, 1)


def default_interrupt_approval(spec: ToolSpec, arguments: dict[str, Any]) -> ToolApprovalDecision:
    if DEFAULT_TOOL_APPROVAL_TRUST_STORE.is_trusted(spec.id):
        return ToolApprovalDecision(action="approve")
    decision = interrupt(
        {
            "type": "tool_approval",
            "message": "检测到需要人工确认的工具调用，请确认执行、拒绝、信任该工具，或输入审查意见让模型重写工具调用。",
            "choices": {"approve": "-y", "deny": "-n", "trust_tool": "-t", "revise": "custom"},
            "requests": [
                {
                    "tool_call_id": "",
                    "tool_name": spec.id,
                    "args": arguments,
                    "summary": spec.id,
                }
            ],
        }
    )
    if _is_trust_tool(decision):
        DEFAULT_TOOL_APPROVAL_TRUST_STORE.trust_tool(spec.id)
        return ToolApprovalDecision(action="approve")
    return parse_approval_decision(decision)


def parse_approval_decision(decision: Any) -> ToolApprovalDecision:
    if _is_approved(decision):
        return ToolApprovalDecision(action="approve")
    if isinstance(decision, dict):
        action = str(decision.get("action") or decision.get("choice") or "").strip().lower()
        if action in {"revise", "retry", "custom", "edit", "rewrite"}:
            return ToolApprovalDecision(action="revise", revision_guidance=_revision_guidance(decision))
    if isinstance(decision, str) and decision.strip().lower() in {"revise", "retry", "custom", "edit", "rewrite"}:
        return ToolApprovalDecision(action="revise", revision_guidance=decision.strip())
    return ToolApprovalDecision(action="deny", revision_guidance=_revision_guidance(decision))


def _is_approved(decision: Any) -> bool:
    if isinstance(decision, bool):
        return decision
    if isinstance(decision, str):
        return decision.strip().lower() in {"-y", "y", "yes", "true", "approve", "approved"}
    if isinstance(decision, dict):
        value = decision.get("approved", decision.get("approve", decision.get("choice")))
        return _is_approved(value)
    return False


def _is_trust_tool(decision: Any) -> bool:
    if isinstance(decision, str):
        return decision.strip().lower() in TRUST_TOOL_ACTIONS or decision.strip().lower() in {"-t", "t", "trust me"}
    if isinstance(decision, dict):
        action = str(decision.get("action") or decision.get("choice") or "").strip().lower()
        if action in TRUST_TOOL_ACTIONS:
            return True
        return bool(decision.get("trust_tool") or decision.get("no_approval"))
    return False


def _revision_guidance(decision: Any) -> str:
    if isinstance(decision, str):
        return decision.strip()
    if isinstance(decision, dict):
        for key in ("revision_guidance", "guidance", "input_text", "message"):
            value = decision.get(key)
            if value:
                return str(value).strip()
    return ""
