from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from combo.tooling.spec import SNAKE_CASE_ID, ToolRiskLevel, ToolRiskResult, ToolSpec


ToolApprovalRequirement = Literal["allow", "ask", "ask_on_risk", "ask_unless_allowed", "deny"]
ToolApprovalPolicyMode = Literal["strict", "allow_below_high", "allow_all", "custom"]
ToolApprovalPolicyAction = Literal["allow", "ask", "deny"]
ToolApprovalOverrideAction = Literal["inherit", "allow", "ask", "deny"]


class ToolApprovalOverrideConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_level: ToolRiskLevel | None = None
    approval: ToolApprovalOverrideAction = "inherit"


class ToolApprovalPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ToolApprovalPolicyMode = "allow_below_high"
    low: ToolApprovalRequirement = "allow"
    medium: ToolApprovalRequirement = "allow"
    high: ToolApprovalRequirement = "ask"
    tool_overrides: dict[str, ToolApprovalOverrideConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _apply_mode_defaults(self) -> "ToolApprovalPolicyConfig":
        if self.mode == "custom":
            return self
        defaults = _mode_defaults(self.mode)
        for field_name, value in defaults.items():
            setattr(self, field_name, value)
        return self

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower().replace("-", "_")
        aliases = {
            "default": "allow_below_high",
            "normal": "allow_below_high",
            "safe": "allow_below_high",
            "standard": "allow_below_high",
            "below_high": "allow_below_high",
            "high_only": "allow_below_high",
            "ask_high": "allow_below_high",
            "ask_all": "strict",
            "always_ask": "strict",
            "read_only": "strict",
            "strict_readonly": "strict",
            "off": "allow_all",
            "disabled": "allow_all",
            "none": "allow_all",
            "no_approval": "allow_all",
            "always_allow": "allow_all",
            "max": "allow_all",
            "highest": "allow_all",
        }
        return aliases.get(normalized, normalized)

    @field_validator("low", "medium", "high", mode="before")
    @classmethod
    def _normalize_requirement(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower().replace("-", "_")
        aliases = {
            "never": "allow",
            "no": "allow",
            "none": "allow",
            "off": "allow",
            "always_allow": "allow",
            "yes": "ask",
            "always": "ask",
            "always_ask": "ask",
            "on": "ask",
            "on_risk": "ask_on_risk",
            "if_risky": "ask_on_risk",
            "when_risky": "ask_on_risk",
            "default": "ask_on_risk",
            "if_needed": "ask_on_risk",
            "inherit": "ask_unless_allowed",
            "deny_all": "deny",
            "block": "deny",
        }
        return aliases.get(normalized, normalized)

    @field_validator("tool_overrides", mode="before")
    @classmethod
    def _normalize_tool_overrides(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        overrides: dict[str, object] = {}
        for raw_key, raw_item in value.items():
            tool_id = str(raw_key or "").strip()
            if not tool_id:
                continue
            normalized_tool_id = tool_id.lower().replace("-", "_")
            if not SNAKE_CASE_ID.fullmatch(normalized_tool_id):
                raise ValueError(f"invalid tool override id: {tool_id}")
            overrides[normalized_tool_id] = raw_item
        return overrides


def tool_approval_policy_action(
    *,
    spec: ToolSpec,
    risk: ToolRiskResult,
    policy: ToolApprovalPolicyConfig,
) -> ToolApprovalPolicyAction:
    if risk.action == "deny":
        return "deny"
    tool_override = policy.tool_overrides.get(spec.id)
    if tool_override is not None and tool_override.approval != "inherit":
        return tool_override.approval
    risk_level = tool_approval_effective_risk_level(spec=spec, risk=risk, policy=policy)
    if policy.mode == "strict":
        return "allow" if _is_strict_read_allowed(spec=spec, risk=risk, risk_level=risk_level) else "ask"
    requirement = _requirement_for_level(policy, risk_level)
    if requirement == "deny":
        return "deny"
    if requirement == "allow":
        return "allow"
    if requirement == "ask":
        return "ask"
    if requirement == "ask_on_risk":
        if risk.action in {"ask", "uncertain"}:
            return "ask"
        return "allow"
    if risk.action == "allow":
        return "allow"
    if risk.action in {"ask", "uncertain", "inherit"}:
        return "ask"
    return "allow"


def tool_approval_effective_risk_level(
    *,
    spec: ToolSpec,
    risk: ToolRiskResult,
    policy: ToolApprovalPolicyConfig,
) -> ToolRiskLevel:
    tool_override = policy.tool_overrides.get(spec.id)
    if tool_override is not None and tool_override.risk_level:
        return tool_override.risk_level
    return risk.risk_level or spec.risk_level


def _mode_defaults(mode: ToolApprovalPolicyMode) -> dict[str, ToolApprovalRequirement]:
    if mode == "strict":
        return {"low": "ask", "medium": "ask", "high": "ask"}
    if mode == "allow_all":
        return {"low": "allow", "medium": "allow", "high": "allow"}
    return {"low": "allow", "medium": "allow", "high": "ask"}


def _requirement_for_level(policy: ToolApprovalPolicyConfig, level: ToolRiskLevel) -> ToolApprovalRequirement:
    if level == "high":
        return policy.high
    if level == "medium":
        return policy.medium
    return policy.low


def _is_strict_read_allowed(*, spec: ToolSpec, risk: ToolRiskResult, risk_level: ToolRiskLevel) -> bool:
    return (
        spec.read_only
        and risk.action == "allow"
        and risk_level == "low"
    )
