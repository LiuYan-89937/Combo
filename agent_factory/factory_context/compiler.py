from __future__ import annotations

from typing import Any

from agent_factory.factory_context.envelope import ArtifactRef, ContextVisibilityRule, FactoryContextEnvelope
from agent_factory.factory_context.ledger import DecisionLedger, EvidenceStore
from agent_factory.factory_context.prompt_registry import PromptTemplateRegistry
from agent_factory.factory_context.tool_policy import tool_policy_for_stage


class NodeContextCompiler:
    """Compile stage-specific Factory context from typed artifact refs.

    The compiler is deliberately conservative: only redacted artifact refs and
    summaries are exposed. Raw state payloads remain in the state/evidence store
    and are not promoted into prompt context by default.
    """

    def __init__(self, prompt_registry: PromptTemplateRegistry | None = None) -> None:
        self.prompt_registry = prompt_registry or PromptTemplateRegistry.default()

    def compile(
        self,
        *,
        stage: str,
        state: Any,
        decision_ledger: DecisionLedger,
        evidence_store: EvidenceStore,
    ) -> FactoryContextEnvelope:
        template = self.prompt_registry.for_stage(stage)
        policy = tool_policy_for_stage(stage)
        return FactoryContextEnvelope(
            stage=stage,
            objective=_objective_for_stage(stage),
            allowed_inputs=_allowed_inputs_for_stage(stage),
            forbidden_inputs=_forbidden_inputs_for_stage(stage, template.forbidden_context),
            decision_refs=[*decision_ledger.refs(), *artifact_refs_from_state(state)],
            evidence_refs=evidence_store.refs(),
            available_tools=policy.allowed_tools,
            model_profile=template.model_profile,
            prompt_template_id=template.template_id,
            output_schema=template.schema_name or template.output_artifact_type,
            validation_rules=_validation_rules_for_stage(stage),
            visibility_rules=[
                ContextVisibilityRule(pattern="api_key|secret|authorization|token|jwt", action="redact", reason="secret"),
                ContextVisibilityRule(pattern="raw_webpage|raw_search|stdout|stderr", action="exclude", reason="raw evidence"),
            ],
        )


def artifact_refs_from_state(state: Any) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for attr, artifact_type in [
        ("requirement_understanding", "RequirementUnderstanding"),
        ("capability_plan", "CapabilityPlan"),
        ("condition_plan", "ConditionPlan"),
        ("resource_need_plan", "ResourceNeedPlan"),
        ("readiness_decision", "ReadinessDecision"),
        ("implementation_plan", "ImplementationPlan"),
        ("production_summary", "ProductionSummary"),
    ]:
        value = getattr(state, attr, None)
        if value:
            refs.append(
                ArtifactRef(
                    artifact_id=attr,
                    artifact_type=artifact_type,
                    summary=_summary_for_value(value),
                    safe_for_prompt=True,
                )
            )
    if getattr(state, "package_path", None):
        refs.append(
            ArtifactRef(
                artifact_id="package_path",
                artifact_type="AgentPackagePath",
                summary=str(state.package_path),
                path=str(state.package_path),
                safe_for_prompt=True,
            )
        )
    return refs


def _objective_for_stage(stage: str) -> str:
    return {
        "classify_factory_intent": "Decide whether the input is an Agent creation request.",
        "analyze_requirement": "Extract confirmed goal, role, audience, and missing essentials.",
        "plan_capability_preconditions": "Create a high-level capability plan before condition/resource setup.",
        "analyze_tool_preconditions": "Identify task completion conditions without treating guesses as facts.",
        "discover_resources": "Bind only real local resources mentioned in the requirement.",
        "factory_web_research": "Extract evidence from user-provided URLs and same-domain docs.",
        "probe_environment": "Collect read-only local/system evidence and build resource contracts.",
        "resolve_readiness": "Classify blocking, deferred, and warning conditions.",
        "generate_tool_scripts": "Generate code from confirmed contracts and implementation plan only.",
        "run_generated_tool_tests": "Run sandboxed tests and report warnings without polluting real resources.",
        "complete": "Summarize outputs, pending config, warnings, and next steps.",
    }.get(stage, f"Run Factory stage: {stage}.")


def _allowed_inputs_for_stage(stage: str) -> list[str]:
    mapping = {
        "classify_factory_intent": ["requirement"],
        "analyze_requirement": ["requirement", "factory_intent"],
        "plan_capability_preconditions": ["RequirementUnderstanding", "AgentPackagePrimitives"],
        "analyze_tool_preconditions": ["RequirementUnderstanding", "CapabilityPlan", "AgentPackagePrimitives"],
        "discover_resources": ["requirement", "ResourceNeedPlan"],
        "factory_web_research": ["ResourceNeedPlan", "user_provided_urls"],
        "probe_environment": ["ResourceNeedPlan", "EvidenceReport"],
        "resolve_readiness": ["ConditionPlan", "ResourceNeedPlan", "EvidenceReport", "ResourceContractSet"],
        "generate_tool_scripts": ["ResourceContractSet", "ImplementationPlan", "EvidenceSummary"],
        "run_generated_tool_tests": ["GeneratedToolDraft", "ResourceContractSet", "sandbox_context"],
        "complete": ["reports", "ReadinessDecision", "package_path"],
    }
    return mapping.get(stage, ["typed_artifact_refs"])


def _forbidden_inputs_for_stage(stage: str, template_forbidden: list[str]) -> list[str]:
    default = ["api_key", "secret", "authorization", "raw_model_reasoning"]
    stage_specific = {
        "generate_tool_scripts": ["raw_webpage", "raw_search", "unconfirmed_conditions", "runtime_secrets"],
        "analyze_tool_preconditions": ["raw_webpage", "tool_code", "runtime_secrets"],
        "factory_web_research": ["api_key", "secret", "unbounded_web_search"],
        "resolve_readiness": ["raw_webpage", "tool_code"],
    }.get(stage, [])
    return sorted(set([*default, *template_forbidden, *stage_specific]))


def _validation_rules_for_stage(stage: str) -> list[str]:
    if stage == "resolve_readiness":
        return ["Produce blocking/deferred/warning categories.", "Resolution options must be related and at most 3."]
    if stage == "generate_tool_scripts":
        return ["Do not invent facts.", "Use ResourceContract and external_config keys.", "No direct network imports."]
    if stage == "factory_web_research":
        return ["Only user-provided URLs and same-domain related pages.", "Unconfirmed fields must be unresolved."]
    return ["Output must match declared schema.", "Secrets must be redacted."]


def _summary_for_value(value: object) -> str:
    if isinstance(value, dict):
        for key in ("summary", "goal", "status", "agent_name"):
            item = value.get(key)
            if item:
                return str(item)[:240]
        return ", ".join(str(key) for key in list(value.keys())[:6])
    return str(value)[:240]
