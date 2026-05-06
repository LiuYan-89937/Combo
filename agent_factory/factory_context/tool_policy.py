from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NodeToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    policy_id: str
    stage: str
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


STAGE_TOOL_POLICIES: dict[str, NodeToolPolicy] = {
    "classify_factory_intent": NodeToolPolicy(
        policy_id="intent.no_tools",
        stage="classify_factory_intent",
        allowed_tools=[],
        notes=["Use task model only; no filesystem, shell, browser, or network tools."],
    ),
    "analyze_requirement": NodeToolPolicy(
        policy_id="requirement.no_tools",
        stage="analyze_requirement",
        allowed_tools=[],
    ),
    "identify_conditions": NodeToolPolicy(
        policy_id="conditions.no_side_effects",
        stage="identify_conditions",
        allowed_tools=[],
        forbidden_tools=["shell.write", "file.write", "browser.fetch"],
    ),
    "collect_evidence": NodeToolPolicy(
        policy_id="evidence.readonly",
        stage="collect_evidence",
        allowed_tools=["file.stat", "data.schema.readonly", "command.which", "url.fetch.same_domain"],
        forbidden_tools=["file.write", "file.delete", "shell.write"],
    ),
    "generate_tools": NodeToolPolicy(
        policy_id="tool_generation.model_only",
        stage="generate_tools",
        allowed_tools=[],
        forbidden_tools=["raw_webpage", "secrets", "unconfirmed_conditions"],
    ),
    "tool_testing": NodeToolPolicy(
        policy_id="tool_testing.sandbox",
        stage="tool_testing",
        allowed_tools=["sandbox.subprocess", "sandbox.resource_copy"],
    ),
    "summary": NodeToolPolicy(
        policy_id="summary.readonly",
        stage="summary",
        allowed_tools=["report.read"],
    ),
}


def tool_policy_for_stage(stage: str) -> NodeToolPolicy:
    if stage in STAGE_TOOL_POLICIES:
        return STAGE_TOOL_POLICIES[stage]
    if stage in {"factory_web_research", "probe_environment", "discover_resources"}:
        return STAGE_TOOL_POLICIES["collect_evidence"]
    if stage in {"analyze_tool_preconditions", "plan_capability_preconditions"}:
        return STAGE_TOOL_POLICIES["identify_conditions"]
    if stage in {"generate_tool_scripts", "generate_tool_tests"}:
        return STAGE_TOOL_POLICIES["generate_tools"]
    if stage in {"static_check_tool_scripts", "run_generated_tool_tests", "repair_tool_tests"}:
        return STAGE_TOOL_POLICIES["tool_testing"]
    if stage in {"complete", "record_factory_memory"}:
        return STAGE_TOOL_POLICIES["summary"]
    return NodeToolPolicy(policy_id=f"{stage}.default", stage=stage)
