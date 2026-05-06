from __future__ import annotations

import json
import re
from typing import Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.context import ContextBundle
from agent_factory.tools.router import ToolResultEnvelope


class ContextBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    max_prompt_tokens: int = Field(default=16000, gt=0)
    reserved_response_tokens: int = Field(default=2000, ge=0)
    reserved_tool_schema_tokens: int = Field(default=2000, ge=0)
    reserved_system_tokens: int = Field(default=1200, ge=0)
    evidence_budget: int = Field(default=3000, ge=0)
    memory_budget: int = Field(default=2000, ge=0)


ContextPriorityName = Literal[
    "system_instruction",
    "active_user_task",
    "pending_tool_observation",
    "recent_messages",
    "memory_summary",
    "retrieved_context",
    "historical_messages",
]


class ContextPriority(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    order: list[ContextPriorityName] = Field(
        default_factory=lambda: [
            "system_instruction",
            "active_user_task",
            "pending_tool_observation",
            "recent_messages",
            "memory_summary",
            "retrieved_context",
            "historical_messages",
        ]
    )


class MessageWindowResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    recent_messages: list[BaseMessage] = Field(default_factory=list)
    historical_messages: list[BaseMessage] = Field(default_factory=list)
    compression_triggered: bool = False


class MessageWindowPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    max_recent_turns: int = Field(default=8, gt=0)

    def apply(self, messages: list[BaseMessage]) -> MessageWindowResult:
        window = self.max_recent_turns * 2
        if len(messages) <= window:
            return MessageWindowResult(recent_messages=list(messages))
        return MessageWindowResult(
            recent_messages=messages[-window:],
            historical_messages=messages[:-window],
            compression_triggered=True,
        )


class SummaryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enabled: bool = True
    trigger_turns: int = Field(default=12, gt=0)
    max_chars: int = Field(default=2000, gt=0)

    def summarize(
        self,
        messages: list[BaseMessage],
        *,
        existing_summary: str | None = None,
    ) -> str | None:
        if not self.enabled:
            return existing_summary
        user_turns = sum(1 for message in messages if _message_role(message) == "user")
        if user_turns < self.trigger_turns and not existing_summary:
            return None
        lines: list[str] = []
        if existing_summary:
            lines.append(existing_summary)
        for message in messages:
            role = _message_role(message)
            if role not in {"user", "assistant", "tool"}:
                continue
            content = _redact_text(_message_content(message))
            if len(content) > 240:
                content = content[:240] + "...[truncated]"
            lines.append(f"{role}: {content}")
        summary = "\n".join(lines)
        if len(summary) > self.max_chars:
            summary = summary[-self.max_chars :]
        return summary or None


class ToolObservationCompressor(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    max_chars: int = Field(default=3000, gt=0)
    prefer_structured_summary: bool = True

    def compress(self, result: ToolResultEnvelope) -> str:
        if self.prefer_structured_summary and result.observation_summary:
            summary = result.observation_summary
        else:
            summary = json.dumps(
                {
                    "tool_call_id": result.tool_call_id or result.invocation_id,
                    "tool_id": result.tool_id,
                    "status": result.status,
                    "output": result.output,
                    "error": result.error,
                },
                ensure_ascii=False,
                default=str,
            )
        summary = _redact_text(summary)
        if len(summary) > self.max_chars:
            summary = summary[: self.max_chars] + "...[truncated]"
        return summary


class VisibilityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    secret_fields: list[str] = Field(
        default_factory=lambda: [
            "api_key",
            "authorization",
            "jwt",
            "tool_auth_token",
            "secret",
        ]
    )

    def redact_bundle(self, bundle: ContextBundle) -> ContextBundle:
        return ContextBundle(
            visible_to_model=[self.redact_text(item) for item in bundle.visible_to_model],
            visible_to_tools=self.redact_value(bundle.visible_to_tools),
            hidden={key: "[HIDDEN]" for key in bundle.hidden},
            source_ids=list(bundle.source_ids),
        )

    def redact_text(self, value: str) -> str:
        return _redact_text(value, fields=self.secret_fields)

    def redact_value(self, value: Any) -> Any:
        sensitive = {field.lower() for field in self.secret_fields}
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if str(key).lower() in sensitive else self.redact_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.redact_value(item) for item in value]
        if isinstance(value, str):
            return self.redact_text(value)
        return value


class NodeStateReducer(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    allowed_updates: dict[str, set[str]] = Field(
        default_factory=lambda: {
            "model_node": {
                "messages",
                "tool_calls",
                "active_calls",
                "run_phase",
                "answer",
                "error",
                "usage",
                "memory_summary",
                "context_compression_triggered",
            },
            "tool_node": {
                "messages",
                "tool_results",
                "interrupt",
                "run_phase",
                "answer",
                "active_calls",
                "turn_count",
                "error",
            },
        }
    )

    def reduce(
        self,
        node: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> dict[str, Any]:
        allowed = self.allowed_updates.get(node)
        if allowed is None:
            raise ValueError(f"Unknown reducer node: {node}")
        changed = {
            key
            for key in set(before) | set(after)
            if before.get(key) != after.get(key)
        }
        disallowed = sorted(changed.difference(allowed))
        if disallowed:
            raise ValueError(f"{node} attempted to update disallowed fields: {', '.join(disallowed)}")
        return after


def _redact_text(value: str, *, fields: list[str] | None = None) -> str:
    fields = fields or ["api_key", "authorization", "jwt", "tool_auth_token", "secret", "token"]
    redacted = value
    for field in fields:
        redacted = re.sub(
            rf"(?i)({re.escape(field)})\s*[:=]\s*[^\s,;]+",
            rf"\1=[REDACTED]",
            redacted,
        )
    return redacted


def _message_role(message: BaseMessage) -> str:
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    if isinstance(message, SystemMessage):
        return "system"
    return getattr(message, "type", "message")


def _message_content(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)
