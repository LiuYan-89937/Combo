from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_factory.specs import (
    AgentPackagePrimitives,
    EnvironmentProbe,
    EnvironmentProbeReport,
    Metadata,
    PreconditionSpec,
    ReadinessIssue,
    ReadinessOption,
    ReadinessReport,
    ResourceContract,
    ResourceContractsSpec,
    ShellCapabilitySpec,
)
from agent_factory.tools.shell import ControlledShellRunner
from agent_factory.factory.tool_preconditions import RequiredCondition, ToolPreconditionReport
from agent_factory.factory.web_search import WebSearchReport
from agent_factory.factory.web_research import ResearchBriefBundle, ResearchCompletenessReport


LOCAL_RESOURCE_PATTERN = re.compile(r"(?:/|~|\./|\../)[^\s，。；：、'\"]+")


class EnvironmentProbeRunner:
    """Build resource-level readiness facts before tool code is generated."""

    def __init__(self, *, shell_runner: ControlledShellRunner | None = None) -> None:
        self.shell_runner = shell_runner or ControlledShellRunner(timeout_seconds=5)

    def probe(
        self,
        primitives: AgentPackagePrimitives | None,
        *,
        requirement: str,
        start_path: str | Path | None = None,
        tool_precondition_report: dict[str, Any] | ToolPreconditionReport | None = None,
        web_research_report: dict[str, Any] | WebSearchReport | None = None,
        research_brief_report: dict[str, Any] | ResearchBriefBundle | None = None,
        research_completeness_report: dict[str, Any] | ResearchCompletenessReport | None = None,
    ) -> tuple[EnvironmentProbeReport, ResourceContractsSpec, ReadinessReport]:
        metadata = _metadata(primitives, "environment")
        resource_metadata = _metadata(primitives, "resource-contracts")
        readiness_metadata = _metadata(primitives, "readiness")
        resource_inputs = _resource_inputs(primitives, requirement, start_path=start_path)
        contracts = [
            self._probe_resource(source_id, ref, access_mode)
            for source_id, ref, access_mode in resource_inputs
        ]
        tool_preconditions = _coerce_tool_precondition_report(tool_precondition_report)
        web_research = _coerce_web_research_report(web_research_report)
        research_brief = _coerce_research_brief_report(research_brief_report)
        research_completeness = _coerce_research_completeness_report(research_completeness_report)
        contracts.extend(
            _condition_contracts(tool_preconditions, web_research, research_brief, research_completeness)
        )
        preconditions = _preconditions_from_contracts(contracts)
        preconditions.extend(
            _generic_preconditions(
                tool_preconditions,
                web_research,
                research_brief=research_brief,
                research_completeness=research_completeness,
                contracts=contracts,
            )
        )
        probes: list[EnvironmentProbe] = []
        resource_contracts = ResourceContractsSpec(
            schema_version="0.1",
            metadata=resource_metadata,
            resources=contracts,
        )
        readiness = _readiness_from_contracts(
            readiness_metadata,
            contracts,
            preconditions,
            tool_preconditions=tool_preconditions,
            web_research=web_research,
            research_brief=research_brief,
            research_completeness=research_completeness,
        )
        report = EnvironmentProbeReport(
            schema_version="0.1",
            metadata=metadata,
            preconditions=preconditions,
            probes=probes,
            shell_capabilities=[
                ShellCapabilitySpec(
                    id="shell.command",
                    allowed_commands=sorted(self.shell_runner.allowed_commands),
                    proposal_only=True,
                    approval_required=True,
                    sandbox_required=True,
                    timeout_seconds=10,
                )
            ],
        )
        return report, resource_contracts, readiness

    def _probe_resource(
        self,
        source_id: str,
        ref: str,
        access_mode: str,
    ) -> ResourceContract:
        path = Path(ref).expanduser()
        resource_type = _resource_type(path)
        if not path.exists():
            return ResourceContract(
                id=source_id,
                type=resource_type,
                ref=str(path),
                exists=False,
                status="missing",
                access_mode=_access_mode(access_mode),
                details={"reason": "resource path does not exist"},
            )
        if path.is_dir():
            return ResourceContract(
                id=source_id,
                type="directory",
                ref=str(path),
                exists=True,
                status="ready" if path.is_dir() else "error",
                access_mode=_access_mode(access_mode),
                details={
                    "readable": _can_read(path),
                    "writable": _can_write(path),
                },
            )
        return ResourceContract(
            id=source_id,
            type=resource_type,
            ref=str(path),
            exists=True,
            status="ready" if _can_read(path) else "inaccessible",
            access_mode=_access_mode(access_mode),
            details={
                "readable": _can_read(path),
                "writable": _can_write(path.parent),
                "size_bytes": path.stat().st_size if path.exists() else None,
            },
        )

def _resource_inputs(
    primitives: AgentPackagePrimitives | None,
    requirement: str,
    *,
    start_path: str | Path | None,
) -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    values: list[tuple[str, str, str]] = []
    if primitives is not None:
        for source in primitives.knowledge.sources:
            if not source.ref:
                continue
            key = str(Path(source.ref).expanduser())
            seen.add(key)
            values.append((source.id, source.ref, source.access_mode))
    root = Path(start_path or ".").resolve()
    scan_requirement = _remove_urls(requirement)
    for raw in LOCAL_RESOURCE_PATTERN.findall(scan_requirement):
        ref = raw.rstrip(".,;:，。；：、)")
        path = Path(ref).expanduser()
        if not path.is_absolute():
            path = root / path
        key = str(path)
        if key in seen:
            continue
        if not _looks_like_resource_reference(path):
            continue
        seen.add(key)
        values.append((_resource_id(path), str(path), "read_only"))
    return values


def _remove_urls(text: str) -> str:
    return re.sub(r"https?://[^\s，。；：、'\"]+", " ", text)


def _preconditions_from_contracts(contracts: list[ResourceContract]) -> list[PreconditionSpec]:
    preconditions: list[PreconditionSpec] = []
    for resource in contracts:
        if resource.type not in {"file", "directory"}:
            continue
        preconditions.append(
            PreconditionSpec(
                id=f"{resource.id}.exists",
                type="resource_exists",
                description=f"Resource exists: {resource.ref}",
                status="passed" if resource.exists else "failed",
                resource_ref=resource.id,
            )
        )
        if resource.exists:
            preconditions.append(
                PreconditionSpec(
                    id=f"{resource.id}.readable",
                    type="resource_readable",
                    description=f"Resource is readable: {resource.ref}",
                    status="passed" if resource.status in {"ready", "unsupported"} else "failed",
                    resource_ref=resource.id,
                    details=resource.details,
                )
            )
    return preconditions


def _condition_contracts(
    report: ToolPreconditionReport | None,
    web_research: WebSearchReport | None,
    research_brief: ResearchBriefBundle | None,
    research_completeness: ResearchCompletenessReport | None,
) -> list[ResourceContract]:
    if report is None:
        return []
    contracts: list[ResourceContract] = []
    for plan in report.plans:
        probe_by_condition = {target.condition_id: target for target in plan.probe_targets}
        for condition in plan.required_conditions:
            resource_type = _resource_type_from_condition(condition)
            if resource_type is None:
                continue
            status = _resource_status_from_condition(condition, report, web_research, research_brief)
            probe_target = probe_by_condition.get(condition.condition_id)
            contracts.append(
                ResourceContract(
                    id=_resource_contract_id(plan.tool_id, condition),
                    type=resource_type,
                    ref=_condition_ref(condition, probe_target),
                    exists=status == "ready",
                    status=status,  # type: ignore[arg-type]
                    access_mode=_access_mode_from_condition(condition),
                    visible_to_tools=True,
                    sandbox_required=condition.type
                    in {"local_resource", "database_schema", "storage_backend", "data_contract"},
                    details={
                        "tool_id": plan.tool_id,
                        "condition": condition.model_dump(mode="json"),
                        "probe_target": probe_target.model_dump(mode="json") if probe_target else None,
                        "mock_only_requested": report.mock_only_requested,
                        "agent_should_inherit_web_search": plan.agent_should_inherit_web_search,
                        "research_queries": plan.research_queries,
                        "web_research_status": web_research.status if web_research else "skipped",
                        "research_brief": _research_brief_for_prompt(research_brief),
                        "research_completeness": _research_completeness_for_prompt(
                            research_completeness
                        ),
                        "configuration_template": (
                            {
                                "file": "external_config.yaml",
                                "required_values": _runtime_config_values_for_condition(
                                    condition,
                                    research_brief=research_brief,
                                ),
                                "note": "Fill this template before running the Agent against the real external service.",
                            }
                            if _condition_uses_external_config_template(condition)
                            else None
                        ),
                    },
                )
            )
    return contracts


def _generic_preconditions(
    report: ToolPreconditionReport | None,
    web_research: WebSearchReport | None,
    *,
    research_brief: ResearchBriefBundle | None,
    research_completeness: ResearchCompletenessReport | None,
    contracts: list[ResourceContract],
) -> list[PreconditionSpec]:
    if report is None:
        return []
    preconditions: list[PreconditionSpec] = []
    for plan in report.plans:
        for condition in plan.required_conditions:
            if _condition_satisfied_by_contract(condition, contracts):
                status = "passed"
            elif condition.type == "web_research" and _research_evidence_can_generate(
                research_brief,
                research_completeness,
            ):
                status = "passed"
            elif report.mock_only_requested and condition.type in {
                "external_service",
                "credential",
                "mock_fixture",
                "browser_access",
            }:
                status = "passed"
            else:
                status = _precondition_status_from_condition(condition)
            preconditions.append(
                PreconditionSpec(
                    id=condition.condition_id,
                    type=condition.type,
                    description=condition.description,
                    required=condition.required,
                    status=status,
                    resource_ref=_resource_contract_id(plan.tool_id, condition)
                    if _resource_type_from_condition(condition)
                    else None,
                    details={
                        "tool_id": plan.tool_id,
                        "probe_strategy": condition.probe_strategy,
                        "user_input_needed": condition.user_input_needed,
                        "evidence": condition.evidence,
                        "web_research_status": web_research.status if web_research else "skipped",
                        "research_brief_status": (
                            research_brief.brief.status if research_brief is not None else "skipped"
                        ),
                        "research_completeness_status": (
                            research_completeness.status if research_completeness is not None else "skipped"
                        ),
                    },
                )
            )
    return preconditions


def _readiness_from_contracts(
    metadata: Metadata,
    contracts: list[ResourceContract],
    preconditions: list[PreconditionSpec],
    *,
    tool_preconditions: ToolPreconditionReport | None = None,
    web_research: WebSearchReport | None = None,
    research_brief: ResearchBriefBundle | None = None,
    research_completeness: ResearchCompletenessReport | None = None,
) -> ReadinessReport:
    if tool_preconditions is not None and tool_preconditions.mock_only_requested:
        return ReadinessReport(
            schema_version="0.1",
            metadata=metadata,
            status="mock_only_allowed",
            issues=[
                ReadinessIssue(
                    code="mock_only_selected",
                    message="User selected mock-only draft for missing external conditions.",
                    severity="warning",
                )
            ],
        )
    failed_required = [item for item in preconditions if item.required and item.status == "failed"]
    issues = [
        ReadinessIssue(
            code=item.type,
            message="Readiness precondition failed.",
            severity="error",
            resource_id=item.resource_ref,
            details=_readiness_issue_details(item),
        )
        for item in failed_required
    ]
    if research_completeness is not None and research_completeness.status in {
        "needs_more_url",
        "unsupported",
    }:
        detail_parts = []
        if research_completeness.missing_urls:
            detail_parts.append("缺少 URL: " + ", ".join(research_completeness.missing_urls[:5]))
        if research_completeness.missing_facts:
            detail_parts.append("缺少事实: " + ", ".join(research_completeness.missing_facts[:8]))
        message = research_completeness.summary
        if detail_parts:
            message = f"{message} ({'; '.join(detail_parts)})"
        issues.append(
            ReadinessIssue(
                code="research_completeness",
                message=message,
                severity="error",
            )
        )
    if not failed_required:
        return ReadinessReport(schema_version="0.1", metadata=metadata, status="ready")
    if _can_continue_with_external_config_template(
        failed_required,
        contracts,
        web_research=web_research,
        research_brief=research_brief,
        research_completeness=research_completeness,
    ):
        completeness_issue = _research_completeness_warning(research_completeness)
        return ReadinessReport(
            schema_version="0.1",
            metadata=metadata,
            status="ready",
            issues=[
                ReadinessIssue(
                    code="external_config_template_required",
                    message="External configuration template is required.",
                    severity="warning",
                ),
                *[
                    ReadinessIssue(
                        code=item.type,
                        message="Readiness precondition deferred to external_config.yaml.",
                        severity="warning",
                        resource_id=item.resource_ref,
                        details=_readiness_issue_details(item),
                    )
                    for item in failed_required
                ],
                *([completeness_issue] if completeness_issue is not None else []),
            ],
        )
    options = _readiness_options_for_failed_preconditions(failed_required)
    return ReadinessReport(
        schema_version="0.1",
        metadata=metadata,
        status="needs_user_input",
        issues=issues,
        options=options,
    )


def _readiness_issue_details(precondition: PreconditionSpec) -> dict[str, Any]:
    return {
        "precondition_id": precondition.id,
        "precondition_type": precondition.type,
        "target": _target_from_precondition_description(precondition.description),
        "source_description": precondition.description,
        "probe_status": precondition.status,
        "resource_ref": precondition.resource_ref,
        "probe_details": precondition.details,
    }


def _target_from_precondition_description(description: str) -> str:
    if ":" not in description:
        return description
    return description.split(":", 1)[1].strip() or description


def _resource_contract_id(tool_id: str, condition: RequiredCondition) -> str:
    raw = f"{tool_id}_{condition.type}"
    return re.sub(r"[^a-zA-Z0-9_]+", "_", raw).strip("_").lower() or "condition_resource"


def _resource_type_from_condition(condition: RequiredCondition) -> str | None:
    if condition.type in {"local_resource", "database_schema"}:
        return None
    if condition.type == "external_service":
        return "external_api"
    if condition.type == "web_research":
        return "web_search"
    if condition.type == "browser_access":
        return "http_endpoint"
    if condition.type == "mcp_server":
        return "mcp"
    if condition.type == "storage_backend":
        return "storage"
    if condition.type == "python_package":
        return "python_package"
    if condition.type == "system_command":
        return "system_command"
    if condition.type == "data_contract":
        return "data_contract"
    return None


def _condition_uses_external_config_template(condition: RequiredCondition) -> bool:
    return condition.type in {"external_service", "credential", "mock_fixture", "data_contract"}


def _runtime_config_values_for_condition(
    condition: RequiredCondition,
    *,
    research_brief: ResearchBriefBundle | None,
) -> list[str]:
    if research_brief is not None and research_brief.brief.recommended_config_fields:
        return [field.key for field in research_brief.brief.recommended_config_fields]
    if condition.type == "external_service":
        return ["api_docs_url", "credential_ref", "operation_endpoint", "operation_method"]
    if condition.type == "credential":
        return ["credential_ref"]
    if condition.type == "mock_fixture":
        return ["test_fixture"]
    if condition.type == "data_contract":
        return ["request_schema", "response_schema", "error_schema"]
    return []


def _can_continue_with_external_config_template(
    failed_required: list[PreconditionSpec],
    contracts: list[ResourceContract],
    *,
    web_research: WebSearchReport | None,
    research_brief: ResearchBriefBundle | None,
    research_completeness: ResearchCompletenessReport | None,
) -> bool:
    if not _research_evidence_can_generate(research_brief, research_completeness):
        return False
    failed_types = {item.type for item in failed_required}
    deferable = {"external_service", "credential", "mock_fixture", "data_contract"}
    if not failed_types or not failed_types.issubset(deferable):
        return False
    return any(resource.type == "external_api" for resource in contracts)


def _resource_status_from_condition(
    condition: RequiredCondition,
    report: ToolPreconditionReport,
    web_research: WebSearchReport | None,
    research_brief: ResearchBriefBundle | None = None,
) -> str:
    if report.mock_only_requested and condition.type in {
        "external_service",
        "credential",
        "mock_fixture",
        "browser_access",
    }:
        return "ready"
    if condition.type == "web_research" and _research_brief_is_usable(research_brief):
        return "ready"
    if condition.status == "satisfied":
        return "ready"
    if condition.status == "skipped" and not condition.required:
        return "unsupported"
    if condition.status == "failed":
        return "error"
    return "missing"


def _precondition_status_from_condition(condition: RequiredCondition) -> str:
    if condition.status == "satisfied":
        return "passed"
    if condition.status == "skipped" and not condition.required:
        return "skipped"
    if condition.required and condition.status in {"unknown", "missing", "failed"}:
        return "failed"
    if condition.user_input_needed and condition.required:
        return "failed"
    return "skipped"


def _condition_satisfied_by_contract(
    condition: RequiredCondition,
    contracts: list[ResourceContract],
) -> bool:
    if condition.type == "local_resource":
        return any(resource.status == "ready" for resource in contracts)
    return False


def _condition_ref(condition: RequiredCondition, probe_target: object | None) -> str | None:
    evidence = condition.evidence or {}
    for key in ("ref", "path", "url", "endpoint", "provider", "module", "command"):
        value = evidence.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    ref = getattr(probe_target, "ref", None)
    if isinstance(ref, str) and ref.strip():
        return ref.strip()
    return None


def _access_mode_from_condition(condition: RequiredCondition) -> str:
    evidence_mode = str((condition.evidence or {}).get("access_mode") or "").strip().lower()
    if evidence_mode in {"read_write", "write", "rw"}:
        return "read_write"
    return "read_only"


def _readiness_options_for_failed_preconditions(
    failed_required: list[PreconditionSpec],
) -> list[ReadinessOption]:
    if not failed_required:
        return []
    return [
        ReadinessOption(
            id="provide_missing_information",
            label="补充缺失信息",
            description="根据上方校验结果补充真实路径、配置、权限、契约或测试样例。",
            action="ask_user",
        ),
        ReadinessOption(
            id="generate_draft_only",
            label="只生成草稿",
            description="暂不执行工具测试，生成不可直接运行的草稿包。",
            action="generate_draft_only",
        ),
    ]


def _coerce_tool_precondition_report(
    value: dict[str, Any] | ToolPreconditionReport | None,
) -> ToolPreconditionReport | None:
    if value is None:
        return None
    if isinstance(value, ToolPreconditionReport):
        return value
    return ToolPreconditionReport.model_validate(value)


def _coerce_web_research_report(value: dict[str, Any] | WebSearchReport | None) -> WebSearchReport | None:
    if value is None:
        return None
    if isinstance(value, WebSearchReport):
        return value
    return WebSearchReport.model_validate(value)


def _coerce_research_brief_report(
    value: dict[str, Any] | ResearchBriefBundle | None,
) -> ResearchBriefBundle | None:
    if value is None:
        return None
    if isinstance(value, ResearchBriefBundle):
        return value
    return ResearchBriefBundle.model_validate(value)


def _coerce_research_completeness_report(
    value: dict[str, Any] | ResearchCompletenessReport | None,
) -> ResearchCompletenessReport | None:
    if value is None:
        return None
    if isinstance(value, ResearchCompletenessReport):
        return value
    return ResearchCompletenessReport.model_validate(value)


def _research_brief_is_usable(research_brief: ResearchBriefBundle | None) -> bool:
    return research_brief is not None and research_brief.brief.status in {
        "resolved",
        "partially_resolved",
    }


def _research_evidence_can_generate(
    research_brief: ResearchBriefBundle | None,
    research_completeness: ResearchCompletenessReport | None,
) -> bool:
    if research_completeness is not None:
        return research_completeness.ok_for_generation
    return _research_brief_is_usable(research_brief)


def _research_completeness_warning(
    research_completeness: ResearchCompletenessReport | None,
) -> ReadinessIssue | None:
    if research_completeness is None or research_completeness.status == "sufficient":
        return None
    if research_completeness.status == "needs_config_values":
        return ReadinessIssue(
            code="external_config_values_required",
            message=(
                "External documentation is sufficient, but runtime configuration keys still need values: "
                + ", ".join(research_completeness.missing_config_keys[:8])
            ),
            severity="warning",
        )
    return ReadinessIssue(
        code="research_completeness_incomplete",
        message=research_completeness.summary,
        severity="error",
    )


def _research_brief_for_prompt(research_brief: ResearchBriefBundle | None) -> dict[str, Any]:
    if research_brief is None:
        return {}
    brief = research_brief.brief
    return {
        "service_id": brief.service_id,
        "service_name": brief.service_name,
        "status": brief.status,
        "confidence": brief.confidence,
        "summary": brief.summary,
        "sources": [source.model_dump(mode="json") for source in brief.sources[:5]],
        "facts": brief.facts,
        "recommended_config_fields": [
            field.model_dump(mode="json") for field in brief.recommended_config_fields
        ],
        "unresolved_fields": brief.unresolved_fields,
        "issues": brief.issues[:10],
    }


def _research_completeness_for_prompt(
    research_completeness: ResearchCompletenessReport | None,
) -> dict[str, Any]:
    if research_completeness is None:
        return {}
    return research_completeness.model_dump(mode="json")


def _metadata(primitives: AgentPackagePrimitives | None, suffix: str) -> Metadata:
    if primitives is None:
        return Metadata(
            name=f"agentfactory-context-first-{suffix}",
            version="1.0.0",
        )
    metadata = primitives.instructions.metadata
    return Metadata(
        name=f"{metadata.name}-{suffix}",
        version=metadata.version,
        description=metadata.description,
        owner=metadata.owner,
    )


def _resource_type(path: Path) -> str:
    if path.is_dir():
        return "directory"
    return "file" if path.exists() or path.suffix else "unknown"


def _access_mode(value: str) -> str:
    return "read_write" if value == "read_write" else "read_only"


def _looks_like_resource_reference(path: Path) -> bool:
    return bool(path.suffix) or path.exists()


def _resource_id(path: Path) -> str:
    stem = path.stem or path.name or "resource"
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", stem).strip("_").lower()
    if not normalized:
        normalized = "resource"
    if normalized[0].isdigit():
        normalized = f"resource_{normalized}"
    return normalized


def _can_read(path: Path) -> bool:
    try:
        if path.is_dir():
            next(path.iterdir(), None)
            return True
        with path.open("rb"):
            return True
    except OSError:
        return False


def _can_write(path: Path) -> bool:
    return path.exists() and path.is_dir()
