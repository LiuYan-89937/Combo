from __future__ import annotations

import importlib.util
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
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
    SQLiteColumnContract,
    SQLiteTableContract,
)
from agent_factory.tools.shell import ControlledShellRunner
from agent_factory.factory.tool_preconditions import RequiredCondition, ToolPreconditionReport
from agent_factory.factory.web_search import WebSearchReport
from agent_factory.factory.web_research import ResearchBriefBundle, ResearchCompletenessReport


LOCAL_RESOURCE_PATTERN = re.compile(r"(?:/|~|\./|\../)[^\s，。；：、'\"]+")


class EnvironmentProbeRunner:
    """Build resource-level readiness facts before tool code is generated."""

    def __init__(self, *, shell_runner: ControlledShellRunner | None = None) -> None:
        self.shell_runner = shell_runner or ControlledShellRunner(
            allowed_commands={"sqlite3", "python", "python3"},
            timeout_seconds=5,
        )

    def probe(
        self,
        primitives: AgentPackagePrimitives,
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
        probes = [
            EnvironmentProbe(
                id="python.sqlite3",
                type="python_module_available",
                status="passed" if importlib.util.find_spec("sqlite3") is not None else "failed",
                message="Python sqlite3 module availability.",
            )
        ]
        sqlite3_path = shutil.which("sqlite3")
        probes.append(
            EnvironmentProbe(
                id="cli.sqlite3",
                type="cli_available",
                status="passed" if sqlite3_path else "skipped",
                message="sqlite3 CLI is optional; Python sqlite3 is the primary probe/runtime.",
                details={"path": sqlite3_path} if sqlite3_path else {},
            )
        )
        if sqlite3_path:
            result = self.shell_runner.run([sqlite3_path, "--version"])
            probes.append(
                EnvironmentProbe(
                    id="cli.sqlite3.version",
                    type="cli_version",
                    status="passed" if result.ok else "failed",
                    message=result.stdout.strip() or result.stderr.strip() or result.error,
                    details={"return_code": result.return_code},
                )
            )
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
                    allowed_commands=["sqlite3", "python", "python3"],
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
        if resource_type == "sqlite":
            return self._probe_sqlite(source_id, path, access_mode)
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

    def _probe_sqlite(self, source_id: str, path: Path, access_mode: str) -> ResourceContract:
        details: dict[str, Any] = {
            "readable": _can_read(path),
            "writable": _can_write(path.parent),
            "sandbox_copyable": _can_copy_to_sandbox(path),
        }
        tables: list[SQLiteTableContract] = []
        status = "ready"
        try:
            with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
                rows = conn.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
                details["tables"] = [row[0] for row in rows]
                for table_name, create_sql in rows:
                    columns = conn.execute(f"PRAGMA table_info({ _quote_identifier(table_name) })").fetchall()
                    column_contracts = [
                        SQLiteColumnContract(
                            name=str(column[1]),
                            type=str(column[2] or ""),
                            not_null=bool(column[3]),
                            default=None if column[4] is None else str(column[4]),
                            primary_key=bool(column[5]),
                        )
                        for column in columns
                    ]
                    primary_keys = [column.name for column in column_contracts if column.primary_key]
                    required_columns = [
                        column.name
                        for column in column_contracts
                        if column.not_null and not column.primary_key and column.default is None
                    ]
                    tables.append(
                        SQLiteTableContract(
                            name=str(table_name),
                            columns=column_contracts,
                            primary_keys=primary_keys,
                            required_columns=required_columns,
                            check_constraints=_extract_check_constraints(str(create_sql or "")),
                        )
                    )
        except sqlite3.Error as error:
            status = "error"
            details["error"] = str(error)
        return ResourceContract(
            id=source_id,
            type="sqlite",
            ref=str(path),
            exists=True,
            status=status,  # type: ignore[arg-type]
            access_mode=_access_mode(access_mode),
            details=details,
            sqlite_tables=tables,
        )


def _resource_inputs(
    primitives: AgentPackagePrimitives,
    requirement: str,
    *,
    start_path: str | Path | None,
) -> list[tuple[str, str, str]]:
    seen: set[str] = set()
    values: list[tuple[str, str, str]] = []
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
        values.append((_resource_id(path), str(path), _access_mode_from_requirement(requirement)))
    return values


def _remove_urls(text: str) -> str:
    return re.sub(r"https?://[^\s，。；：、'\"]+", " ", text)


def _preconditions_from_contracts(contracts: list[ResourceContract]) -> list[PreconditionSpec]:
    preconditions: list[PreconditionSpec] = []
    for resource in contracts:
        if resource.type in {"external_api", "web_search", "http_endpoint", "realtime_data"}:
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
        if resource.type == "sqlite":
            preconditions.append(
                PreconditionSpec(
                    id=f"{resource.id}.sqlite_openable",
                    type="sqlite_openable",
                    description=f"SQLite database can be opened: {resource.ref}",
                    status="passed" if resource.status == "ready" else "failed",
                    resource_ref=resource.id,
                    details=resource.details,
                )
            )
            preconditions.append(
                PreconditionSpec(
                    id=f"{resource.id}.sqlite_schema",
                    type="sqlite_schema_available",
                    description=f"SQLite schema is available: {resource.ref}",
                    status="passed" if resource.sqlite_tables else "failed",
                    resource_ref=resource.id,
                )
            )
            preconditions.append(
                PreconditionSpec(
                    id=f"{resource.id}.sandbox_copyable",
                    type="sandbox_copyable",
                    description=f"SQLite database can be copied into tool-test sandbox: {resource.ref}",
                    status="passed" if resource.details.get("sandbox_copyable") else "failed",
                    resource_ref=resource.id,
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
            message=item.description,
            severity="error",
            resource_id=item.resource_ref,
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
                    message=(
                        "External service details were not fully configured. "
                        "Factory will write external_config.yaml with placeholders; "
                        "fill it before real runtime."
                    ),
                    severity="warning",
                ),
                *[
                    ReadinessIssue(
                        code=item.type,
                        message=f"Deferred to external_config.yaml: {item.description}",
                        severity="warning",
                        resource_id=item.resource_ref,
                    )
                    for item in failed_required
                ],
                *([completeness_issue] if completeness_issue is not None else []),
            ],
        )
    has_missing = any(
        resource.status == "missing" and resource.type in {"file", "directory", "sqlite"}
        for resource in contracts
    )
    options = _readiness_options_for_failed_preconditions(failed_required)
    if has_missing:
        options.insert(
            0,
            ReadinessOption(
                id="create_sample_resource",
                label="创建示例资源",
                description="由用户确认后创建示例数据库或文件，再继续生产。",
                action="create_sample_resource",
            ),
        )
    return ReadinessReport(
        schema_version="0.1",
        metadata=metadata,
        status="needs_user_input",
        issues=issues,
        options=options,
    )


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
    if condition.type == "database_schema":
        return any(
            resource.type == "sqlite" and resource.status == "ready" and resource.sqlite_tables
            for resource in contracts
        )
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
    description = condition.description.lower()
    if any(marker in description for marker in ("write", "create", "update", "delete", "写", "创建", "更新", "删除")):
        return "read_write"
    if condition.type in {"storage_backend", "database_schema"} and "read_write" in str(condition.evidence):
        return "read_write"
    return "read_only"


def _readiness_options_for_failed_preconditions(
    failed_required: list[PreconditionSpec],
) -> list[ReadinessOption]:
    options: list[ReadinessOption] = []

    def add(option: ReadinessOption) -> None:
        if any(existing.id == option.id for existing in options):
            return
        options.append(option)

    failed_types = {item.type for item in failed_required}
    if failed_types.intersection({"external_service", "credential"}):
        add(
            ReadinessOption(
                id="provide_external_url",
                label="提供官方文档 URL",
                description="粘贴外部服务的官方文档、API Reference、OpenAPI 或购买页 URL。",
                action="provide_api_docs",
            )
        )
        add(
            ReadinessOption(
                id="provide_external_config_values",
                label="提供配置项名称",
                description="像 .env 一样给出需要的键名，例如 MOJI_APP_CODE、WEATHER_DOC_URL。",
                action="ask_user",
            )
        )
    if "web_research" in failed_types:
        add(
            ReadinessOption(
                id="provide_external_url",
                label="提供官方文档 URL",
                description="Factory 不自动搜索；请提供要提取的单个官方页面 URL。",
                action="provide_api_docs",
            )
        )
    if failed_types.intersection(
        {
            "local_resource",
            "database_schema",
            "resource_exists",
            "resource_readable",
            "resource_writable",
            "sqlite_openable",
            "sqlite_schema_available",
            "sandbox_copyable",
        }
    ):
        add(
            ReadinessOption(
                id="replace_resource_path",
                label="提供新的资源路径",
                description="用户提供一个已存在、可访问的本地资源路径。",
                action="replace_resource_path",
            )
        )
    if failed_types.intersection({"python_package", "runtime_dependency", "system_command"}):
        add(
            ReadinessOption(
                id="install_dependency",
                label="安装或声明依赖",
                description="补齐 Python 包、系统命令或运行时依赖后继续。",
                action="install_dependency",
            )
        )
    if failed_types.intersection({"permission", "human_approval"}):
        add(
            ReadinessOption(
                id="grant_permission",
                label="确认权限与审批",
                description="明确允许的动作、审批方式和禁止边界。",
                action="grant_permission",
            )
        )
    if "mock_fixture" in failed_types:
        add(
            ReadinessOption(
                id="provide_test_fixture",
                label="提供测试 fixture",
                description="提供稳定样例输入/输出、测试收件箱或 mock 响应。",
                action="provide_test_fixture",
            )
        )
        add(
            ReadinessOption(
                id="use_mock_only",
                label="只生成 mock-only 草稿",
                description="明确接受本地模拟实现，不声称是真实实时数据。",
                action="use_mock_only",
            )
        )
    if "browser_access" in failed_types:
        add(
            ReadinessOption(
                id="configure_browser",
                label="配置浏览/网页访问",
                description="提供目标 URL、访问频率、允许域名和测试快照。",
                action="configure_browser",
            )
        )
    if "mcp_server" in failed_types:
        add(
            ReadinessOption(
                id="configure_mcp",
                label="配置 MCP Server",
                description="提供 MCP server 命令、transport、工具列表和测试 fixture。",
                action="configure_mcp",
            )
        )
    if "schedule" in failed_types:
        add(
            ReadinessOption(
                id="configure_schedule",
                label="配置定时策略",
                description="明确频率、时区、触发条件和失败重试策略。",
                action="configure_schedule",
            )
        )
    if "storage_backend" in failed_types:
        add(
            ReadinessOption(
                id="configure_storage",
                label="配置存储",
                description="提供运行状态、历史记录或比对结果的存储位置。",
                action="configure_storage",
            )
        )
    if "data_contract" in failed_types:
        add(
            ReadinessOption(
                id="provide_data_contract",
                label="补充数据契约",
                description="明确输入字段、输出字段、边界样例和错误样例。",
                action="ask_user",
            )
        )
    add(
        ReadinessOption(
            id="generate_draft_only",
            label="只生成草稿",
            description="暂不执行工具测试，生成不可直接运行的草稿包。",
            action="generate_draft_only",
        )
    )
    return options


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


def _metadata(primitives: AgentPackagePrimitives, suffix: str) -> Metadata:
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
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        return "sqlite"
    if path.suffix:
        return "file"
    return "unknown"


def _access_mode(value: str) -> str:
    return "read_write" if value == "read_write" else "read_only"


def _access_mode_from_requirement(value: str) -> str:
    lowered = value.lower()
    if any(marker in lowered for marker in ("创建", "更新", "修改", "关闭", "写", "insert", "update", "create")):
        return "read_write"
    return "read_only"


def _looks_like_resource_reference(path: Path) -> bool:
    return path.suffix.lower() in {
        ".csv",
        ".db",
        ".duckdb",
        ".json",
        ".md",
        ".sqlite",
        ".sqlite3",
        ".tsv",
        ".txt",
        ".yaml",
        ".yml",
    } or path.exists()


def _resource_id(path: Path) -> str:
    stem = path.stem or path.name or "resource"
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"sqlite", "sqlite3", "db", "duckdb"} and not stem.endswith("_sqlite"):
        stem = f"{stem}_sqlite"
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


def _can_copy_to_sandbox(path: Path) -> bool:
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            shutil.copy2(path, Path(tmpdir) / path.name)
        return True
    except OSError:
        return False


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _extract_check_constraints(create_sql: str) -> list[str]:
    return [match.group(0) for match in re.finditer(r"CHECK\s*\([^)]+\)", create_sql, flags=re.IGNORECASE)]
