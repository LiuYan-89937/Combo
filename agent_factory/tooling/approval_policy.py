from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from agent_factory.tooling.spec import ToolRiskLevel, ToolRiskResult, ToolSpec


ToolApprovalRequirement = Literal["allow", "ask", "ask_on_risk", "ask_unless_allowed", "deny"]
ToolApprovalPolicyMode = Literal["standard", "strict", "allow_all", "custom"]
ToolApprovalPolicyAction = Literal["allow", "ask", "deny"]


class ToolApprovalPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ToolApprovalPolicyMode = "standard"
    low: ToolApprovalRequirement = "ask_on_risk"
    medium: ToolApprovalRequirement = "ask_unless_allowed"
    high: ToolApprovalRequirement = "ask"

    @model_validator(mode="after")
    def _apply_mode_defaults(self) -> "ToolApprovalPolicyConfig":
        if self.mode == "custom":
            return self
        explicit_fields = set(self.model_fields_set)
        defaults = _mode_defaults(self.mode)
        for field_name, value in defaults.items():
            if field_name not in explicit_fields:
                setattr(self, field_name, value)
        return self

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower().replace("-", "_")
        aliases = {
            "default": "standard",
            "normal": "standard",
            "safe": "standard",
            "ask_all": "strict",
            "always_ask": "strict",
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


def default_tool_approval_policy() -> ToolApprovalPolicyConfig:
    policy = ToolApprovalPolicyConfig(mode=_env("AGENTFACTORY_TOOL_APPROVAL_MODE", "standard"))
    overrides = {
        "low": _env("AGENTFACTORY_TOOL_APPROVAL_LOW", ""),
        "medium": _env("AGENTFACTORY_TOOL_APPROVAL_MEDIUM", ""),
        "high": _env("AGENTFACTORY_TOOL_APPROVAL_HIGH", ""),
    }
    custom = {key: value for key, value in overrides.items() if value}
    if custom:
        policy = policy.model_copy(update={"mode": "custom", **custom})
        policy = ToolApprovalPolicyConfig.model_validate(policy.model_dump(mode="json"))
    return policy


def resolve_tool_approval_policy(package_policy: ToolApprovalPolicyConfig | None) -> ToolApprovalPolicyConfig:
    policy = default_tool_approval_policy()
    if package_policy is None:
        return policy
    payload = policy.model_dump(mode="json")
    explicit_fields = set(package_policy.model_fields_set)
    if "mode" in explicit_fields:
        payload.update(_mode_defaults(package_policy.mode))
        payload["mode"] = package_policy.mode
    for field_name in ("low", "medium", "high"):
        if field_name in explicit_fields:
            payload[field_name] = getattr(package_policy, field_name)
    return ToolApprovalPolicyConfig.model_validate(payload)


def tool_approval_policy_action(
    *,
    spec: ToolSpec,
    risk: ToolRiskResult,
    policy: ToolApprovalPolicyConfig,
) -> ToolApprovalPolicyAction:
    if risk.action == "deny":
        return "deny"
    requirement = _requirement_for_level(policy, risk.risk_level or spec.risk_level)
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


def _mode_defaults(mode: ToolApprovalPolicyMode) -> dict[str, ToolApprovalRequirement]:
    if mode == "strict":
        return {"low": "ask", "medium": "ask", "high": "ask"}
    if mode == "allow_all":
        return {"low": "allow", "medium": "allow", "high": "allow"}
    return {"low": "ask_on_risk", "medium": "ask_unless_allowed", "high": "ask"}


def _requirement_for_level(policy: ToolApprovalPolicyConfig, level: ToolRiskLevel) -> ToolApprovalRequirement:
    if level == "high":
        return policy.high
    if level == "medium":
        return policy.medium
    return policy.low


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()
