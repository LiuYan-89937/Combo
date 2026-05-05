from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PromptTemplateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    template_id: str
    stage: str
    input_artifact_types: list[str] = Field(default_factory=list)
    output_artifact_type: str
    forbidden_context: list[str] = Field(default_factory=list)
    tool_policy_id: str
    model_profile: str = "task"
    schema_name: str | None = None


class PromptTemplateRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    templates: dict[str, PromptTemplateSpec] = Field(default_factory=dict)

    @classmethod
    def default(cls) -> "PromptTemplateRegistry":
        registry = cls()
        for spec in DEFAULT_TEMPLATES:
            registry.templates[spec.stage] = spec
        return registry

    def for_stage(self, stage: str) -> PromptTemplateSpec:
        return self.templates.get(
            stage,
            PromptTemplateSpec(
                template_id=f"{stage}.default",
                stage=stage,
                output_artifact_type="UnknownArtifact",
                tool_policy_id=f"{stage}.default",
            ),
        )


DEFAULT_TEMPLATES = [
    PromptTemplateSpec(
        template_id="intent.classifier.v1",
        stage="classify_factory_intent",
        output_artifact_type="FactoryIntentClassification",
        forbidden_context=["raw_evidence", "shell", "browser"],
        tool_policy_id="intent.no_tools",
        schema_name="FactoryIntentClassification",
    ),
    PromptTemplateSpec(
        template_id="requirement.understanding.v1",
        stage="analyze_requirement",
        output_artifact_type="RequirementUnderstanding",
        forbidden_context=["raw_webpage", "secrets", "tool_code"],
        tool_policy_id="requirement.no_tools",
        schema_name="RequirementAnalysis",
    ),
    PromptTemplateSpec(
        template_id="conditions.semantic.v1",
        stage="analyze_tool_preconditions",
        input_artifact_types=["RequirementUnderstanding", "CapabilityPlan"],
        output_artifact_type="ConditionPlan",
        forbidden_context=["raw_webpage", "secrets", "tool_code"],
        tool_policy_id="conditions.no_side_effects",
        schema_name="ToolPreconditionReport",
    ),
    PromptTemplateSpec(
        template_id="evidence.collect.v1",
        stage="factory_web_research",
        input_artifact_types=["ResourceNeedPlan"],
        output_artifact_type="EvidenceReport",
        forbidden_context=["secrets", "unbounded_web_search"],
        tool_policy_id="evidence.readonly",
        schema_name="ResearchBrief",
    ),
    PromptTemplateSpec(
        template_id="tools.generate.v1",
        stage="generate_tool_scripts",
        input_artifact_types=["ResourceContractSet", "ImplementationPlan"],
        output_artifact_type="GeneratedToolDraft",
        forbidden_context=["raw_webpage", "api_key", "secret", "unconfirmed_conditions"],
        tool_policy_id="tool_generation.model_only",
        model_profile="main",
    ),
]

