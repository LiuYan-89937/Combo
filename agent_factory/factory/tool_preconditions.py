from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
    "sqlite_schema",
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
    inheritance = (web_config or WebSearchConfig()).agent_web_inheritance
    return (
        MessageBuilder.start()
        .system(
            "You are AgentFactory's semantic precondition planner for tool creation. "
            "Use the task model. Return exactly one JSON object matching ToolPreconditionReport. "
            "Semantic reasoning is primary; keyword rules are only a safety fallback. "
            "Do not return legacy keys such as tools, external_tool_count, capability_type, "
            "requires_api_key, or requires_web_search."
        )
        .user(
            "Analyze the hidden and explicit conditions that must exist before Factory can generate "
            "each tool implementation. Do not lock the analysis to external HTTP/API needs. Identify "
            "local resources, runtime dependencies, Python packages, system commands, database schemas, "
            "external services, credentials, permissions, human approval, sandbox needs, mock fixtures, "
            "browser access, MCP servers, storage backends, schedules, web research, and data contracts.\n\n"
            f"Requirement:\n{requirement}\n\n"
            f"Agent goal: {primitives.instructions.goal}\n"
            f"Agent boundaries: {json.dumps(primitives.instructions.boundaries, ensure_ascii=False)}\n"
            f"Tool drafts:\n{json.dumps(tool_inputs, ensure_ascii=False, indent=2)}\n\n"
            f"Agent runtime web_search inheritance policy: {inheritance}\n\n"
            "For each plan:\n"
            "- required_conditions must use only these type values: "
            f"{', '.join(get_args(ConditionType))}.\n"
            "- Each condition needs condition_id, type, required, status, description, "
            "probe_strategy, user_input_needed, evidence.\n"
            "- Mark status='missing' and user_input_needed=true when user must provide a URL, "
            "credential, local path, fixture, permission, schedule, schema, provider, or approval policy.\n"
            "- Use probe_targets for conditions Factory can check locally or via controlled tools.\n"
            "- Add risk_controls for writes, deletes, payments, emails, shell/browser/network, "
            "generated code, or sensitive data.\n"
            "- Use web_research only when Factory needs current public docs or API behavior while building.\n"
            "- Only set agent_should_inherit_web_search when the generated Agent itself must search web "
            "at runtime under explicit bounds.\n\n"
            "Examples:\n"
            "- 'track competitor page changes' implies browser_access/http target URL, schedule, "
            "storage_backend, mock_fixture, permission, and maybe web_research.\n"
            "- 'generate daily report and send email' implies data source, email credential, send "
            "permission, test inbox/mock fixture, schedule, human_approval.\n"
            "- 'organize local PDFs' implies local_resource directory, python_package/runtime parser, "
            "output permission, sandbox, data_contract; it should not be treated as an external API."
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
) -> ToolPreconditionReport | None:
    if model_service is None or _provider_name(model_service) == "fake":
        return None
    try:
        request = build_tool_precondition_request(
            primitives,
            requirement,
            web_config=web_config,
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
        if inheritance != "explicit":
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
            "agent_should_inherit_web_search": (
                model_plan.agent_should_inherit_web_search
                or rule_plan.agent_should_inherit_web_search
            ),
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
    lowered = text.lower()
    plan = ToolPreconditionPlan(tool_id=tool_id, mock_only_allowed=mock_only)
    if _mentions_sqlite(lowered):
        plan.capability_kind = "database"
        _add_condition(
            plan,
            _condition(
                tool_id,
                "database_schema",
                "SQLite/database schema must be known before writing SQL tools.",
                probe_strategy="sqlite_schema",
                user_input_needed=False,
                evidence={"rule": "sqlite_or_database_reference"},
            ),
        )
        _add_condition(
            plan,
            _condition(
                tool_id,
                "local_resource",
                "Database file or connection resource must be available.",
                probe_strategy="local_path",
                user_input_needed=True,
                evidence={"rule": "database_resource_reference"},
            ),
        )
        _add_condition(plan, _sandbox_condition(tool_id))
    if _mentions_local_files(lowered):
        plan.capability_kind = "file_processing" if plan.capability_kind == "local" else "mixed"
        _add_condition(
            plan,
            _condition(
                tool_id,
                "local_resource",
                "Local file or directory must exist and be readable before tool generation.",
                probe_strategy="local_path",
                user_input_needed=True,
                evidence={"rule": "local_path_or_file_task"},
            ),
        )
        _add_condition(plan, _sandbox_condition(tool_id))
    if _mentions_pdf(lowered):
        plan.capability_kind = "file_processing"
        _add_condition(
            plan,
            _condition(
                tool_id,
                "python_package",
                "PDF parsing dependency must be available or explicitly selected.",
                probe_strategy="python_module",
                user_input_needed=True,
                evidence={"suggested_modules": ["pypdf", "pdfplumber"]},
            ),
        )
        _add_condition(
            plan,
            _condition(
                tool_id,
                "data_contract",
                "PDF input/output contract must be defined for reliable tests.",
                probe_strategy="data_contract_review",
                user_input_needed=True,
            ),
        )
    if _mentions_browser_or_page(lowered):
        plan.capability_kind = "browser"
        _add_condition(
            plan,
            _condition(
                tool_id,
                "browser_access",
                "Target URL and allowed browser/HTTP access must be provided.",
                probe_strategy="browser_check",
                user_input_needed=True,
                evidence={"rule": "page_tracking_or_browser_task"},
            ),
        )
        _add_condition(
            plan,
            _condition(
                tool_id,
                "storage_backend",
                "A storage backend is needed to compare page changes over time.",
                probe_strategy="storage_check",
                user_input_needed=True,
            ),
        )
        _add_condition(plan, _mock_fixture_condition(tool_id))
        _add_web_research(plan, tool_id, lowered)
    if _mentions_external_service(lowered):
        plan.capability_kind = (
            "external_service" if plan.capability_kind == "local" else plan.capability_kind
        )
        _add_condition(
            plan,
            _condition(
                tool_id,
                "external_service",
                "External service provider, endpoint, and allowed operations must be specified.",
                probe_strategy="user_input",
                user_input_needed=True,
                evidence={"rule": "external_service_or_realtime_task"},
            ),
        )
        _add_condition(
            plan,
            _condition(
                tool_id,
                "credential",
                "Credential or explicit no-auth provider choice is required for external service calls.",
                probe_strategy="credential_check",
                user_input_needed=True,
            ),
        )
        _add_condition(plan, _mock_fixture_condition(tool_id))
        _add_web_research(plan, tool_id, lowered)
    if _mentions_email(lowered):
        plan.capability_kind = "communication"
        _add_condition(
            plan,
            _condition(
                tool_id,
                "external_service",
                "Email provider or SMTP/API endpoint must be configured.",
                probe_strategy="user_input",
                user_input_needed=True,
            ),
        )
        _add_condition(
            plan,
            _condition(
                tool_id,
                "credential",
                "Email sending credentials are required.",
                probe_strategy="credential_check",
                user_input_needed=True,
            ),
        )
        _add_condition(
            plan,
            _condition(
                tool_id,
                "permission",
                "Sending permission and allowed recipient/test inbox policy must be confirmed.",
                probe_strategy="permission_check",
                user_input_needed=True,
            ),
        )
        _add_condition(plan, _mock_fixture_condition(tool_id))
        _add_risk_control(plan, "human_approval", "Email sending must require explicit approval or dry-run tests.")
    if _mentions_schedule(lowered):
        plan.capability_kind = "scheduled_task" if plan.capability_kind == "local" else plan.capability_kind
        _add_condition(
            plan,
            _condition(
                tool_id,
                "schedule",
                "Schedule frequency, timezone, and persistence policy must be defined.",
                probe_strategy="schedule_check",
                user_input_needed=True,
            ),
        )
        _add_condition(
            plan,
            _condition(
                tool_id,
                "storage_backend",
                "Scheduled task state and run history need a storage backend.",
                probe_strategy="storage_check",
                user_input_needed=True,
            ),
        )
    if _mentions_mcp(lowered):
        plan.capability_kind = "mcp"
        _add_condition(
            plan,
            _condition(
                tool_id,
                "mcp_server",
                "MCP server command, transport, and tool contract must be configured.",
                probe_strategy="mcp_health",
                user_input_needed=True,
            ),
        )
    if _mentions_shell(lowered):
        _add_condition(
            plan,
            _condition(
                tool_id,
                "system_command",
                "Allowed shell commands/scripts must be explicitly declared.",
                probe_strategy="system_command",
                user_input_needed=True,
            ),
        )
        _add_risk_control(plan, "sandbox", "Shell execution must run inside a sandbox.")
        _add_risk_control(plan, "allowlist", "Shell execution must use an allowlist.")
    if _mentions_write_or_high_risk((operation_text or text).lower()):
        _add_condition(
            plan,
            _condition(
                tool_id,
                "human_approval",
                "Write, send, delete, payment, or other side-effect operations require approval policy.",
                probe_strategy="manual_review",
                user_input_needed=True,
                evidence={"rule": "side_effect_or_high_risk_operation"},
            ),
        )
        _add_risk_control(plan, "human_approval", "Human confirmation is required for side effects.")
    if not plan.required_conditions:
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
    plan.agent_should_inherit_web_search = (
        inheritance == "explicit"
        and any(condition.type in {"web_research", "browser_access"} for condition in plan.required_conditions)
        and _agent_runtime_search_needed(lowered)
    )
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


def _mock_fixture_condition(tool_id: str) -> RequiredCondition:
    return _condition(
        tool_id,
        "mock_fixture",
        "Deterministic test fixture or mock response is required before tests can pass safely.",
        probe_strategy="mock_fixture",
        user_input_needed=True,
    )


def _add_web_research(plan: ToolPreconditionPlan, tool_id: str, text: str) -> None:
    _add_condition(
        plan,
        _condition(
            tool_id,
            "web_research",
            "Factory should research current public docs/API behavior before implementation.",
            required=False,
            status="unknown",
            probe_strategy="web_search",
            user_input_needed=False,
        ),
    )
    plan.research_queries = _merge_unique([*plan.research_queries, *_search_queries(tool_id, text)])[:5]


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


def _mentions_sqlite(text: str) -> bool:
    return any(marker in text for marker in ["sqlite", ".sqlite", ".sqlite3", ".db", "数据库", "database", "sql"])


def _mentions_local_files(text: str) -> bool:
    return bool(re.search(r"(?:/|~|\./|\../)[^\s，。；：、'\"]+", text)) or any(
        marker in text
        for marker in ["本地文件", "本地目录", "local file", "local directory", "csv", "excel", "xlsx", "pdf"]
    )


def _mentions_pdf(text: str) -> bool:
    return "pdf" in text or "文档整理" in text or "整理文档" in text


def _mentions_browser_or_page(text: str) -> bool:
    return any(
        marker in text
        for marker in [
            "browser",
            "网页",
            "页面",
            "官网",
            "竞品",
            "爬取",
            "抓取",
            "网站",
            "url",
            "http",
            "https",
            "page",
            "site",
            "website",
        ]
    )


def _mentions_external_service(text: str) -> bool:
    return any(
        marker in text
        for marker in [
            "weather",
            "天气",
            "实时",
            "current",
            "live",
            "stock",
            "股票",
            "汇率",
            "价格",
            "price",
            "news",
            "新闻",
            "api",
            "endpoint",
            "外部服务",
            "第三方",
            "联网",
            "上网",
        ]
    )


def _mentions_email(text: str) -> bool:
    return any(marker in text for marker in ["email", "mail", "smtp", "邮件", "发信", "发送日报", "日报"])


def _mentions_schedule(text: str) -> bool:
    return any(
        marker in text
        for marker in ["schedule", "cron", "daily", "weekly", "每天", "每周", "定时", "周期", "监控", "盯住"]
    )


def _mentions_mcp(text: str) -> bool:
    return "mcp" in text


def _mentions_shell(text: str) -> bool:
    return any(marker in text for marker in ["shell", "命令行", "脚本", "bash", "terminal", "终端"])


def _mentions_write_or_high_risk(text: str) -> bool:
    text = re.sub(
        r"创建(?:一个|一名)?\s*(?:agent|助手|智能体|机器人)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"create\s+(?:an?\s+)?(?:agent|assistant|bot)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return any(
        marker in text
        for marker in [
            "create",
            "update",
            "delete",
            "remove",
            "send",
            "pay",
            "refund",
            "close",
            "创建",
            "更新",
            "修改",
            "删除",
            "发送",
            "支付",
            "退款",
            "关闭",
            "写",
        ]
    )


def _agent_runtime_search_needed(text: str) -> bool:
    return any(marker in text for marker in ["实时", "latest", "current", "最新", "上网", "联网", "搜索", "weather", "天气"])


def _mock_only_requested(text: str) -> bool:
    return bool(
        re.search(
            r"mock[-_ ]?only|只生成.*(mock|模拟|草稿)|本地模拟|模拟实现|generate_draft_only",
            text,
            flags=re.IGNORECASE,
        )
    )


def _search_queries(tool_id: str, text: str) -> list[str]:
    named_weather_services = _named_weather_services(text)
    if named_weather_services:
        queries: list[str] = []
        for service in named_weather_services:
            queries.extend(
                [
                    f"{service} API 官方文档 endpoint 鉴权 示例返回",
                    f"{service} 天气 API 空气质量 预报 官方接口",
                ]
            )
        return _merge_unique(queries)[:5]
    if "weather" in text or "天气" in text:
        return [
            "weather API official documentation current weather endpoint",
            "free weather API current weather official docs",
        ]
    if "stock" in text or "股票" in text:
        return ["stock quote API official documentation latest price"]
    if "news" in text or "新闻" in text:
        return ["news API official documentation latest headlines"]
    if any(marker in text for marker in ["email", "smtp", "邮件"]):
        return ["email sending API SMTP official documentation"]
    if any(marker in text for marker in ["竞品", "网页", "官网", "page", "site"]):
        return [f"{tool_id} website monitoring change detection best practices"]
    return [f"{tool_id} API official documentation"]


def _named_weather_services(text: str) -> list[str]:
    values: list[str] = []
    for marker in ["moji weather", "mojiweather", "墨迹"]:
        if marker in text:
            values.append("墨迹天气")
    for match in re.finditer(r"([\u4e00-\u9fffA-Za-z0-9_-]{2,24}?天气)", text):
        value = _clean_named_weather_service(match.group(1).strip())
        if value and value not in {"查询天气", "实时天气", "天气"}:
            values.append(value)
    return _merge_unique(values)


def _clean_named_weather_service(value: str) -> str:
    if "墨迹" in value:
        return "墨迹天气"
    return re.sub(
        r"^(?:帮我|请|创建|建立|生成|一个|一款|能够|可以|用于|查询)+",
        "",
        value,
    ).strip()


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
