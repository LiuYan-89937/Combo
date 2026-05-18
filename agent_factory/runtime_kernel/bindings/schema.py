from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ServiceKind = Literal[
    "model_service",
    "tool_registry",
    "memory_store",
    "memory_system",
    "knowledge_engine",
    "context_engine",
    "policy_engine",
    "observability_manager",
    "checkpointer",
    "harness_bridge",
]

HookPoint = Literal[
    "pre_cognitive",
    "post_cognitive",
    "pre_operational",
    "post_operational",
    "pre_governance",
    "post_governance",
    "pre_terminal",
    "post_terminal",
    "on_interrupt",
    "on_resume",
]

BindingType = Literal[
    "prompt",
    "tool_access",
    "policy_profile",
    "strategy_profile",
    "output_formatter",
    "custom",
]


class ServiceBindingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: str
    kind: ServiceKind
    required: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class NodeBindingTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    impl: str


class PromptBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_id: str
    template: str
    variables: list[str] = Field(default_factory=list)


class ToolAccessBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_tool_ids: list[str] = Field(default_factory=list)
    approval_policy: str = "standard"


class PolicyProfileBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    rules: dict[str, Any] = Field(default_factory=dict)


class StrategyProfileBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)


class OutputFormatterBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    formatter_id: str
    mode: str = "identity"
    config: dict[str, Any] = Field(default_factory=dict)


class CustomBindingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extension_id: str
    schema_version: str = "v0"
    purpose: str
    config: dict[str, Any] = Field(default_factory=dict)


StandardNodeBindingPayload = (
    PromptBindingPayload
    | ToolAccessBindingPayload
    | PolicyProfileBindingPayload
    | StrategyProfileBindingPayload
    | OutputFormatterBindingPayload
    | CustomBindingPayload
)


class NodeBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str
    binding_type: BindingType
    target: NodeBindingTarget
    payload: StandardNodeBindingPayload

    @model_validator(mode="before")
    @classmethod
    def _coerce_payload_for_binding_type(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        binding_type = data.get("binding_type")
        payload = data.get("payload")
        payload_model = _payload_model_for_binding_type(binding_type)
        if payload_model is not None and isinstance(payload, dict):
            data = dict(data)
            data["payload"] = payload_model.model_validate(payload)
        return data

    @model_validator(mode="after")
    def _payload_matches_binding_type(self) -> "NodeBinding":
        payload_model = _payload_model_for_binding_type(self.binding_type)
        if payload_model is None:
            return self
        if not isinstance(self.payload, payload_model):
            raise ValueError(f"payload must match binding_type={self.binding_type}")
        return self


class HookBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    binding_id: str
    hook_point: HookPoint
    enabled: bool = True
    order: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class BindingSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    services: list[ServiceBindingSpec] = Field(default_factory=list)
    node_bindings: list[NodeBinding] = Field(default_factory=list)
    hooks: list[HookBinding] = Field(default_factory=list)


def _payload_model_for_binding_type(binding_type: Any) -> type[BaseModel] | None:
    return {
        "prompt": PromptBindingPayload,
        "tool_access": ToolAccessBindingPayload,
        "policy_profile": PolicyProfileBindingPayload,
        "strategy_profile": StrategyProfileBindingPayload,
        "output_formatter": OutputFormatterBindingPayload,
        "custom": CustomBindingPayload,
    }.get(str(binding_type))
