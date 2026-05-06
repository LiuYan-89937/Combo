from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agent_factory.factory_context import FactoryContextEnvelope, apply_context_envelope
from agent_factory.factory.web_search import WebSearchConfig
from agent_factory.model import LLMRequest, MessageBuilder, ModelConfigError, ModelService
from agent_factory.specs import AgentPackagePrimitives


ConditionType = Literal[
    "local_resource",
    "runtime_dependency",
    "python_package",
    "system_command",
    "database_schema",
    "external_service",
    "credential",
    "permission",
    "human_approval",
    "sandbox",
    "mock_fixture",
    "browser_access",
    "mcp_server",
    "storage_backend",
    "schedule",
    "web_research",
    "data_contract",
]
ConditionStatus = Literal["unknown", "satisfied", "missing", "failed", "skipped"]
ProbeStrategy = Literal[
    "none",
    "local_path",
    "python_module",
    "system_command",
    "web_search",
    "user_input",
    "manual_review",
    "mock_fixture",
    "mcp_health",
    "browser_check",
    "credential_check",
    "permission_check",
    "schedule_check",
    "storage_check",
    "data_contract_review",
]
RiskControlType = Literal[
    "human_approval",
    "sandbox",
    "redaction",
    "allowlist",
    "rate_limit",
    "dry_run",
    "trace",
    "mock_fixture",
    "permission_gate",
]
CapabilityKind = Literal[
    "local",
    "database",
    "file_processing",
    "browser",
    "mcp",
    "external_service",
    "communication",
    "scheduled_task",
    "computation",
    "knowledge",
    "mixed",
]


class RequiredCondition(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    condition_id: str
    type: ConditionType
    required: bool = True
    status: ConditionStatus = "unknown"
    description: str
    probe_strategy: ProbeStrategy = "none"
    user_input_needed: bool = False
    evidence: dict[str, Any] = Field(default_factory=dict)


class ProbeTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    target_id: str
    condition_id: str
    type: ProbeStrategy
    ref: str | None = None
    command: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class RiskControl(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    control_id: str
    type: RiskControlType
    required: bool = True
    description: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ToolPreconditionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tool_id: str
    capability_kind: CapabilityKind = "local"
    required_conditions: list[RequiredCondition] = Field(default_factory=list)
    missing_conditions: list[str] = Field(default_factory=list)
    probe_targets: list[ProbeTarget] = Field(default_factory=list)
    user_questions: list[dict[str, Any]] = Field(default_factory=list)
    risk_controls: list[RiskControl] = Field(default_factory=list)
    research_queries: list[str] = Field(default_factory=list)
    mock_only_allowed: bool = False
    agent_should_inherit_web_search: bool = False
    reason: str | None = None

    @model_validator(mode="after")
    def _derive_missing_conditions(self) -> "ToolPreconditionPlan":
        if not self.missing_conditions:
            object.__setattr__(
                self,
                "missing_conditions",
                [
                    condition.condition_id
                    for condition in self.required_conditions
                    if _condition_is_missing(condition)
                ],
            )
        object.__setattr__(self, "research_queries", _merge_unique(self.research_queries)[:5])
        return self


class ToolPreconditionReport(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    plans: list[ToolPreconditionPlan] = Field(default_factory=list)
    mock_only_requested: bool = False
    agent_web_inheritance: Literal["explicit", "never", "ask"] = "explicit"
    source: str = "rule_fallback"

    @property
    def condition_count(self) -> int:
        return sum(len(plan.required_conditions) for plan in self.plans)

    @property
    def missing_required_conditions(self) -> list[RequiredCondition]:
        return [
            condition
            for plan in self.plans
            for condition in plan.required_conditions
            if _condition_is_missing(condition)
        ]


def analyze_tool_preconditions(
    primitives: AgentPackagePrimitives,
    requirement: str,
    *,
    web_config: WebSearchConfig | None = None,
    model_service: ModelService | None = None,
    context_envelope: FactoryContextEnvelope | None = None,
) -> ToolPreconditionReport:
    rule_report = analyze_tool_preconditions_by_rules(
        primitives,
        requirement,
        web_config=web_config,
    )
    model_report = _analyze_tool_preconditions_with_model(
        primitives,
        requirement,
        web_config=web_config,
        model_service=model_service,
        context_envelope=context_envelope,
    )
    if model_report is None:
        return rule_report
    return _merge_model_and_rule_reports(model_report, rule_report)


def analyze_capability_preconditions(
    capabilities: list[dict[str, Any]],
    requirement: str,
    *,
    web_config: WebSearchConfig | None = None,
    model_service: ModelService | None = None,
    context_envelope: FactoryContextEnvelope | None = None,
) -> ToolPreconditionReport:
    normalized = _normalize_capability_inputs(capabilities, requirement)
    rule_report = _analyze_capability_preconditions_by_rules(
        normalized,
        requirement,
        web_config=web_config,
    )
    model_report = _analyze_capability_preconditions_with_model(
        normalized,
        requirement,
        web_config=web_config,
        model_service=model_service,
        context_envelope=context_envelope,
    )
    if model_report is None:
        return rule_report
    return _merge_model_and_rule_reports(model_report, rule_report)


def analyze_tool_preconditions_by_rules(
    primitives: AgentPackagePrimitives,
    requirement: str,
    *,
    web_config: WebSearchConfig | None = None,
) -> ToolPreconditionReport:
    inheritance = (web_config or WebSearchConfig()).agent_web_inheritance
    mock_only = _mock_only_requested(requirement)
    plans: list[ToolPreconditionPlan] = []
    for tool_id, description in _iter_tools(primitives):
        text = " ".join(
            [
                str(tool_id or ""),
                str(description or ""),
                str(primitives.instructions.goal or ""),
                str(requirement or ""),
            ]
        )
        plans.append(
            _rule_plan_for_tool(
                tool_id,
                text,
                operation_text=" ".join([str(tool_id or ""), str(description or "")]),
                inheritance=inheritance,
                mock_only=mock_only,
            )
        )
    return ToolPreconditionReport(
        plans=plans,
        mock_only_requested=mock_only,
        agent_web_inheritance=inheritance,
        source="rule_fallback",
    )


def _analyze_capability_preconditions_by_rules(
    capabilities: list[dict[str, str]],
    requirement: str,
    *,
    web_config: WebSearchConfig | None = None,
) -> ToolPreconditionReport:
    inheritance = (web_config or WebSearchConfig()).agent_web_inheritance
    mock_only = _mock_only_requested(requirement)
    plans = [
        _rule_plan_for_tool(
            capability["capability_id"],
            " ".join([capability["capability_id"], capability["description"], requirement]),
            operation_text=" ".join([capability["capability_id"], capability["description"]]),
            inheritance=inheritance,
            mock_only=mock_only,
        )
        for capability in capabilities
    ]
    return ToolPreconditionReport(
        plans=plans,
        mock_only_requested=mock_only,
        agent_web_inheritance=inheritance,
        source="rule_fallback",
    )


def _analyze_capability_preconditions_with_model(
    capabilities: list[dict[str, str]],
    requirement: str,
    *,
    web_config: WebSearchConfig | None,
    model_service: ModelService | None,
    context_envelope: FactoryContextEnvelope | None,
) -> ToolPreconditionReport | None:
    if model_service is None or _provider_name(model_service) == "fake":
        return None
    try:
        request = apply_context_envelope(
            _build_capability_precondition_request(
                capabilities,
                requirement,
                web_config=web_config,
            ),
            context_envelope,
        )
        result = asyncio.run(
            model_service.generate_task_structured(
                request,
                schema=ToolPreconditionReport.model_json_schema(),
                schema_name="ToolPreconditionReport",
            )
        )
        if result.error:
            return None
        report = ToolPreconditionReport.model_validate(result.data)
    except (ModelConfigError, ValidationError, TypeError, ValueError, RuntimeError):
        return None
    return _normalize_capability_model_report(report, capabilities, web_config=web_config)


def _build_capability_precondition_request(
    capabilities: list[dict[str, str]],
    requirement: str,
    *,
    web_config: WebSearchConfig | None = None,
) -> LLMRequest:
    schema = ToolPreconditionReport.model_json_schema()
    return (
        MessageBuilder.start()
        .system(
            "You are AgentFactory's context-first condition planner. "
            "Analyze task completion conditions before AgentPackage primitives are generated. "
            "Return exactly one JSON object matching ToolPreconditionReport."
        )
        .user(
            "Identify every condition required to complete the user's requested Agent behavior. "
            "Do not classify complexity by tool count. Do not lock conditions to local/external only. "
            "Detect implicit local resources, databases, files, web/API docs, browser access, credentials, "
            "permissions, storage, schedules, MCP, human approval, sandbox, test fixtures, and data contracts.\n\n"
            f"Requirement:\n{requirement}\n\n"
            "Capability candidates inferred from requirement understanding:\n"
            f"{json.dumps(capabilities, ensure_ascii=False, indent=2)}\n\n"
            "Rules:\n"
            "- Create one plan per capability_id.\n"
            "- Use only these condition type values: "
            f"{', '.join(get_args(ConditionType))}.\n"
            "- Mark runtime secrets/keys as credential and missing/deferred via user_input_needed=true.\n"
            "- If an external service is needed and the user provided documentation URLs, record them in evidence.url.\n"
            "- If docs are absent or insufficient, add web_research/user_input conditions.\n"
            "- Generated agents must not inherit open web_search/browser tools unless the requirement explicitly asks for runtime browsing/search.\n"
            "- Never request or include actual secret values."
        )
        .request(
            response_format="json_schema",
            json_schema=schema,
            json_schema_name="ToolPreconditionReport",
            json_schema_strict=True,
            metadata={
                "phase": "context_first_conditions",
                "model_role": "task",
                "agent_web_inheritance": (web_config or WebSearchConfig()).agent_web_inheritance,
            },
        )
    )


def _normalize_capability_model_report(
    report: ToolPreconditionReport,
    capabilities: list[dict[str, str]],
    *,
    web_config: WebSearchConfig | None,
) -> ToolPreconditionReport:
    known_ids = {capability["capability_id"] for capability in capabilities}
    plans = [plan for plan in report.plans if plan.tool_id in known_ids]
    existing = {plan.tool_id for plan in plans}
    for capability in capabilities:
        if capability["capability_id"] not in existing:
            plans.append(ToolPreconditionPlan(tool_id=capability["capability_id"]))
    return report.model_copy(
        update={
            "plans": plans,
            "agent_web_inheritance": (web_config or WebSearchConfig()).agent_web_inheritance,
            "source": "task_model",
        }
    )


def _normalize_capability_inputs(
    capabilities: list[dict[str, Any]],
    requirement: str,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for index, capability in enumerate(capabilities, start=1):
        raw_id = str(capability.get("capability_id") or capability.get("id") or f"capability_{index}")
        capability_id = re.sub(r"[^a-zA-Z0-9_]+", "_", raw_id).strip("_").lower()
        if not capability_id:
            capability_id = f"capability_{index}"
        description = str(capability.get("description") or capability.get("goal") or requirement)
        normalized.append({"capability_id": capability_id, "description": description})
    if not normalized:
        normalized.append({"capability_id": "conversation", "description": requirement})
    return normalized



def build_tool_precondition_request(
    primitives: AgentPackagePrimitives,
    requirement: str,
    *,
    web_config: WebSearchConfig | None = None,
) -> LLMRequest:
    tool_inputs = [
        {"tool_id": tool_id, "description": description}
        for tool_id, description in _iter_tools(primitives)
    ]
    schema = ToolPreconditionReport.model_json_schema()
    return (
        MessageBuilder.start()
        .system(
            "You are AgentFactory's semantic precondition planner for tool creation. "
            "Use the task model. Return exactly one JSON object matching ToolPreconditionReport. "
            "Semantic reasoning is primary; local code only supplies generic safety defaults. "
            "Do not return legacy keys such as tools, external_tool_count, capability_type, "
            "requires_api_key, or requires_web_search."
        )
        .user(
            "Analyze the hidden and explicit conditions that must exist before Factory can generate "
            "each tool implementation. Do not lock the analysis to a predefined domain. Use the schema "
            "to describe only the conditions supported by the user's requirement and available evidence.\n\n"
            f"Requirement:\n{requirement}\n\n"
            f"Agent goal: {primitives.instructions.goal}\n"
            f"Agent boundaries: {json.dumps(primitives.instructions.boundaries, ensure_ascii=False)}\n"
            f"Tool drafts:\n{json.dumps(tool_inputs, ensure_ascii=False, indent=2)}\n\n"
            "For each plan:\n"
            "- required_conditions must use only these type values: "
            f"{', '.join(get_args(ConditionType))}.\n"
            "- Each condition needs condition_id, type, required, status, description, "
            "probe_strategy, user_input_needed, evidence.\n"
            "- Mark status='missing' and user_input_needed=true when user must provide a URL, "
            "credential, local path, fixture, permission, schedule, schema, provider, or approval policy.\n"
            "- Use probe_targets only for conditions Factory can check from declared evidence or controlled tools.\n"
            "- Add risk_controls only when the requirement, package primitives, or evidence explicitly supports them.\n"
            "- Generated agents must not inherit open web_search/browser_fetch tools by default; external docs are "
            "resolved by Factory from user-provided URLs during production."
        )
        .request(
            response_format="json_schema",
            json_schema=schema,
            json_schema_name="ToolPreconditionReport",
            json_schema_strict=True,
            metadata={"phase": "tool_preconditions", "model_role": "task"},
        )
    )


def _analyze_tool_preconditions_with_model(
    primitives: AgentPackagePrimitives,
    requirement: str,
    *,
    web_config: WebSearchConfig | None,
    model_service: ModelService | None,
    context_envelope: FactoryContextEnvelope | None = None,
) -> ToolPreconditionReport | None:
    if model_service is None or _provider_name(model_service) == "fake":
        return None
    try:
        request = apply_context_envelope(
            build_tool_precondition_request(
                primitives,
                requirement,
                web_config=web_config,
            ),
            context_envelope,
        )
        result = asyncio.run(
            model_service.generate_task_structured(
                request,
                schema=ToolPreconditionReport.model_json_schema(),
                schema_name="ToolPreconditionReport",
            )
        )
        if result.error:
            return None
        report = ToolPreconditionReport.model_validate(result.data)
    except (ModelConfigError, ValidationError, TypeError, ValueError, RuntimeError):
        return None
    return _normalize_model_report(report, primitives, web_config=web_config)


def _normalize_model_report(
    report: ToolPreconditionReport,
    primitives: AgentPackagePrimitives,
    *,
    web_config: WebSearchConfig | None,
) -> ToolPreconditionReport:
    known_tool_ids = {tool_id for tool_id, _description in _iter_tools(primitives)}
    inheritance = (web_config or WebSearchConfig()).agent_web_inheritance
    plans = [plan for plan in report.plans if plan.tool_id in known_tool_ids]
    existing = {plan.tool_id for plan in plans}
    for tool_id in known_tool_ids.difference(existing):
        plans.append(ToolPreconditionPlan(tool_id=tool_id))
    normalized: list[ToolPreconditionPlan] = []
    for plan in plans:
        plan.agent_should_inherit_web_search = False
        plan.missing_conditions = [
            condition.condition_id
            for condition in plan.required_conditions
            if _condition_is_missing(condition)
        ]
        normalized.append(plan)
    return report.model_copy(
        update={
            "plans": normalized,
            "agent_web_inheritance": inheritance,
            "source": "task_model",
        }
    )


def _merge_model_and_rule_reports(
    model_report: ToolPreconditionReport,
    rule_report: ToolPreconditionReport,
) -> ToolPreconditionReport:
    rule_by_tool = {plan.tool_id: plan for plan in rule_report.plans}
    merged: list[ToolPreconditionPlan] = []
    for model_plan in model_report.plans:
        rule_plan = rule_by_tool.get(model_plan.tool_id)
        if rule_plan is None:
            merged.append(model_plan)
            continue
        merged.append(_merge_tool_plans(model_plan, rule_plan))
    return model_report.model_copy(
        update={
            "plans": merged,
            "mock_only_requested": model_report.mock_only_requested or rule_report.mock_only_requested,
            "source": "task_model_with_rule_safety",
        }
    )


def _merge_tool_plans(
    model_plan: ToolPreconditionPlan,
    rule_plan: ToolPreconditionPlan,
) -> ToolPreconditionPlan:
    conditions = list(model_plan.required_conditions)
    for condition in rule_plan.required_conditions:
        if condition.type in {"permission", "human_approval", "sandbox", "credential", "mock_fixture"}:
            conditions = _upsert_condition(conditions, condition)
        elif not any(existing.type == condition.type for existing in conditions):
            conditions.append(condition)
    controls = list(model_plan.risk_controls)
    for control in rule_plan.risk_controls:
        if not any(existing.type == control.type for existing in controls):
            controls.append(control)
    probe_targets = list(model_plan.probe_targets)
    for target in rule_plan.probe_targets:
        if not any(existing.target_id == target.target_id for existing in probe_targets):
            probe_targets.append(target)
    research_queries = _merge_unique([*model_plan.research_queries, *rule_plan.research_queries])[:5]
    missing_conditions = [
        condition.condition_id for condition in conditions if _condition_is_missing(condition)
    ]
    capability_kind = (
        rule_plan.capability_kind
        if model_plan.capability_kind == "local" and rule_plan.capability_kind != "local"
        else model_plan.capability_kind
    )
    return model_plan.model_copy(
        update={
            "capability_kind": capability_kind,
            "required_conditions": conditions,
            "missing_conditions": missing_conditions,
            "probe_targets": probe_targets,
            "risk_controls": controls,
            "research_queries": research_queries,
            "mock_only_allowed": model_plan.mock_only_allowed or rule_plan.mock_only_allowed,
            "agent_should_inherit_web_search": False,
        }
    )


def _iter_tools(primitives: AgentPackagePrimitives) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    seen: set[str] = set()
    for toolset in primitives.toolsets.toolsets:
        for tool_id in [*toolset.exposed_tools, *toolset.hidden_tools]:
            if tool_id in seen:
                continue
            seen.add(tool_id)
            values.append((tool_id, toolset.description))
    return values


def _rule_plan_for_tool(
    tool_id: str,
    text: str,
    *,
    operation_text: str | None = None,
    inheritance: str,
    mock_only: bool,
) -> ToolPreconditionPlan:
    plan = ToolPreconditionPlan(tool_id=tool_id, mock_only_allowed=mock_only)
    _add_condition(
        plan,
        _condition(
            tool_id,
            "sandbox",
            "Generated tool must run inside the standard tool sandbox.",
            required=True,
            status="satisfied",
            probe_strategy="none",
            user_input_needed=False,
        ),
    )
    plan.agent_should_inherit_web_search = False
    plan.missing_conditions = [
        condition.condition_id for condition in plan.required_conditions if _condition_is_missing(condition)
    ]
    return plan


def _condition(
    tool_id: str,
    condition_type: ConditionType,
    description: str,
    *,
    required: bool = True,
    status: ConditionStatus = "missing",
    probe_strategy: ProbeStrategy = "none",
    user_input_needed: bool = False,
    evidence: dict[str, Any] | None = None,
) -> RequiredCondition:
    return RequiredCondition(
        condition_id=f"{tool_id}.{condition_type}",
        type=condition_type,
        required=required,
        status=status,
        description=description,
        probe_strategy=probe_strategy,
        user_input_needed=user_input_needed,
        evidence=evidence or {},
    )


def _sandbox_condition(tool_id: str) -> RequiredCondition:
    return _condition(
        tool_id,
        "sandbox",
        "Tool tests and generated code must run in an isolated sandbox.",
        status="satisfied",
        probe_strategy="none",
    )


def _add_condition(plan: ToolPreconditionPlan, condition: RequiredCondition) -> None:
    plan.required_conditions = _upsert_condition(plan.required_conditions, condition)
    if condition.probe_strategy not in {"none", "user_input", "manual_review"}:
        target_id = f"{condition.condition_id}.probe"
        if not any(target.target_id == target_id for target in plan.probe_targets):
            plan.probe_targets.append(
                ProbeTarget(
                    target_id=target_id,
                    condition_id=condition.condition_id,
                    type=condition.probe_strategy,
                    details={"condition_type": condition.type},
                )
            )


def _upsert_condition(
    conditions: list[RequiredCondition],
    condition: RequiredCondition,
) -> list[RequiredCondition]:
    for index, existing in enumerate(conditions):
        if existing.type == condition.type:
            merged_evidence = {**existing.evidence, **condition.evidence}
            conditions[index] = existing.model_copy(
                update={
                    "required": existing.required or condition.required,
                    "status": _merge_status(existing.status, condition.status),
                    "user_input_needed": existing.user_input_needed or condition.user_input_needed,
                    "description": existing.description or condition.description,
                    "probe_strategy": (
                        condition.probe_strategy
                        if existing.probe_strategy == "none"
                        else existing.probe_strategy
                    ),
                    "evidence": merged_evidence,
                }
            )
            return conditions
    return [*conditions, condition]


def _add_risk_control(plan: ToolPreconditionPlan, control_type: RiskControlType, description: str) -> None:
    if any(control.type == control_type for control in plan.risk_controls):
        return
    plan.risk_controls.append(
        RiskControl(
            control_id=f"{plan.tool_id}.{control_type}",
            type=control_type,
            description=description,
        )
    )


def _condition_is_missing(condition: RequiredCondition) -> bool:
    return condition.required and (
        condition.status in {"unknown", "missing", "failed"} or condition.user_input_needed
    )


def _merge_status(left: ConditionStatus, right: ConditionStatus) -> ConditionStatus:
    if "failed" in {left, right}:
        return "failed"
    if "missing" in {left, right}:
        return "missing"
    if "unknown" in {left, right}:
        return "unknown"
    if "satisfied" in {left, right}:
        return "satisfied"
    return "skipped"


def _mock_only_requested(text: str) -> bool:
    return bool(
        re.search(
            r"mock[-_ ]?only|只生成.*(mock|模拟|草稿)|本地模拟|模拟实现|generate_draft_only",
            text,
            flags=re.IGNORECASE,
        )
    )

def _merge_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _provider_name(model_service: ModelService) -> str:
    config = getattr(getattr(model_service, "router", None), "config", None)
    provider = getattr(config, "provider", None)
    return str(provider or "")
