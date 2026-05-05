from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    artifact_id: str
    artifact_type: str
    summary: str = ""
    path: str | None = None
    safe_for_prompt: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextVisibilityRule(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    pattern: str
    action: str = "exclude"
    reason: str = ""


class FactoryContextEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    stage: str
    objective: str
    allowed_inputs: list[str] = Field(default_factory=list)
    forbidden_inputs: list[str] = Field(default_factory=list)
    decision_refs: list[ArtifactRef] = Field(default_factory=list)
    evidence_refs: list[ArtifactRef] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    model_profile: str = "task"
    prompt_template_id: str | None = None
    output_schema: str | None = None
    validation_rules: list[str] = Field(default_factory=list)
    visibility_rules: list[ContextVisibilityRule] = Field(default_factory=list)

    def safe_prompt_context(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "objective": self.objective,
            "allowed_inputs": self.allowed_inputs,
            "decision_refs": [
                ref.model_dump(mode="json") for ref in self.decision_refs if ref.safe_for_prompt
            ],
            "evidence_refs": [
                ref.model_dump(mode="json") for ref in self.evidence_refs if ref.safe_for_prompt
            ],
            "available_tools": self.available_tools,
            "output_schema": self.output_schema,
            "validation_rules": self.validation_rules,
        }

