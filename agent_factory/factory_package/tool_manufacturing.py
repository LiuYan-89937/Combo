from __future__ import annotations

import ast
from contextlib import contextmanager
import json
import os
from pathlib import Path
import py_compile
import re
import shutil
import subprocess
import sys
from tempfile import mkdtemp
from time import perf_counter
from typing import Any, Iterator

from langchain_core.messages import AIMessage, HumanMessage

from agent_factory.factory_package.schemas import (
    ApprovedPackageToolArtifact,
    CapabilityContractOutput,
    InheritedExtensionArtifact,
    PackageToolBuildPlan,
    ToolDesign,
    ToolInheritedExtensionRef,
    ToolImplementationDraft,
    ToolManufacturingCheck,
    ToolManufacturingFailureSummary,
    ToolManufacturingOutput,
    ToolManufacturingReport,
    ToolSourceDecision,
    ToolSpecDraft,
    ToolTrialPlan,
)
from agent_factory.models import get_task_model
from agent_factory.paths import project_root
from agent_factory.runtime_kernel.model_operations import ModelOperationService
from agent_factory.tooling.compiler import ToolCompiler
from agent_factory.tooling.gateway import ToolApprovalDecision
from agent_factory.tooling.builtins.registry import get_builtin_tool_specs
from agent_factory.tooling.factory_extensions import default_factory_extension_root
from agent_factory.tooling.langgraph_node import (
    build_tool_node_runner,
    latest_ai_tool_calls,
    tool_messages_to_runtime_patch,
)
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


TOOL_MANUFACTURING_REPORT_PATH = "reports/tool_manufacturing_report.json"
TOOL_CONTRACT_SMOKE_REPORT_PATH = "reports/tool_contract_smoke_report.json"
TOOL_RESOURCE_PROBE_REPORT_PATH = "reports/tool_resource_probe_report.json"
TOOL_MODEL_TRIAL_REPORT_PATH = "reports/tool_model_trial_report.json"
TOOL_DEPENDENCY_REPORT_PATH = "reports/dependency_install_report.json"
TOOL_TEST_ENV_ROOT = Path(".agentfactory/tool_test_env")
TOOL_MANUFACTURING_ARTIFACT_ROOT = Path(".agentfactory/tool_manufacturing")
SYSTEM_PACKAGE_EXTENSION_ROOT = Path("SystemPackage/extensions")
_EXTERNAL_HOST_PATTERN = re.compile(
    r"(?i)(?:https?://)?"
    r"((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|cn|net|org|io|ai|co|dev|gov|edu|info|biz|top|xyz)(?:\.[a-z]{2})?)"
)
_RESOURCE_FAILURE_CATEGORIES = {"external_resource_unavailable", "unprovenanced_external_source"}


class ToolManufacturingError(RuntimeError):
    pass


def tool_manufacturing_catalog_payload() -> dict[str, Any]:
    builtin_specs = [
        {
            "id": spec.id,
            "description": spec.description,
            "risk_level": spec.risk_level,
            "input_schema": spec.input_schema,
        }
        for spec in get_builtin_tool_specs()
    ]
    return {
        "source_options": ["builtin", "mcp", "skill", "knowledge", "scheduler", "package_generated"],
        "builtin_tools": builtin_specs,
        "inheritable_extensions": _inheritable_extension_catalog(),
        "resource_selector_syntax": {
            "format": "dot_path",
            "examples": ["report_config", "report_config.news_api_key", "report_config.market_symbols"],
            "forbidden_examples": ["resources://report_config", "{{resources.report_config}}", "/runtime/resources"],
        },
        "source_rules": {
            "builtin": "Use existing system tools for filesystem, process, scheduler, knowledge, network, and tool-output work.",
            "mcp": "Use configured MCP tools when an external tool server already owns the capability.",
            "skill": "Use the Skill system tool for procedural capabilities bundled as skills.",
            "knowledge": "Use the knowledge system tool for managed external knowledge.",
            "scheduler": "Use the scheduler system tool for scheduled job management.",
            "package_generated": "Only generate package tool code for deterministic, agent-specific behavior not covered by existing sources.",
        },
    }


def default_tool_manufacturing_output(capability_contract: CapabilityContractOutput) -> ToolManufacturingOutput:
    decisions = [
        ToolSourceDecision(
            tool_id=item.tool_id,
            source=item.source or "package_generated",
            selected_tool_id=item.tool_id if item.source and item.source != "package_generated" else None,
            rationale=item.purpose or f"Manufacture or bind capability for {item.tool_id}.",
            required_by_nodes=list(item.required_by_nodes),
            binding_notes=f"Required by nodes: {', '.join(item.required_by_nodes) or 'unspecified'}",
        )
        for item in capability_contract.tool_specs_to_generate
    ]
    return ToolManufacturingOutput(
        source_decisions=decisions,
        report=ToolManufacturingReport(
            status="valid",
            source_decisions=decisions,
            approved_tool_ids=[],
            warnings=[],
        ),
        manufacturing_summary_text="No package-generated tools were required.",
    )


def finalize_tool_manufacturing_output(
    *,
    factory_run_id: str,
    output: ToolManufacturingOutput,
    capability_contract: CapabilityContractOutput,
    resource_facts: dict[str, Any] | None = None,
    test_env_root: Path = TOOL_TEST_ENV_ROOT,
) -> ToolManufacturingOutput:
    errors = validate_tool_manufacturing_output(output=output, capability_contract=capability_contract)
    checks: list[ToolManufacturingCheck] = list(output.report.checks)
    approved: list[ApprovedPackageToolArtifact] = []
    blocked_tool_ids: list[str] = _unique_strings(list(output.report.blocked_tool_ids))
    inherited_extensions: list[InheritedExtensionArtifact] = []
    if not errors:
        try:
            inherited_extensions = resolve_inherited_extensions(output.source_decisions)
        except ToolManufacturingError as exc:
            errors.append(str(exc))
    if errors:
        return output.model_copy(
            update={
                "approved_package_tools": [],
                "inherited_extensions": [],
                "report": ToolManufacturingReport(
                    status="invalid",
                    source_decisions=output.source_decisions,
                    checks=[
                        ToolManufacturingCheck(
                            name="tool_manufacturing_alignment",
                            status="failed",
                            message="; ".join(errors),
                            failure_summary=ToolManufacturingFailureSummary(
                                tool_id="tool_manufacturing",
                                phase="manufacturing_alignment",
                                category="contract_alignment_error",
                                primary_error="; ".join(errors),
                                suggested_action="Regenerate tool source decisions and artifacts so they match the capability contract.",
                            ),
                        )
                    ],
                    errors=errors,
                ),
            },
            deep=True,
        )

    decisions_by_id = {item.tool_id: item for item in output.source_decisions}
    designs_by_id = {item.tool_id: item for item in output.tool_designs}
    specs_by_id = {item.tool_id: item for item in output.tool_specs}
    impls_by_id = {item.tool_id: item for item in output.implementations}
    trials_by_id = {item.tool_id: item for item in output.trial_plans}
    approved_by_id = {item.tool_id: item for item in output.approved_package_tools}
    blocked_set = set(blocked_tool_ids)

    for tool_id, decision in sorted(decisions_by_id.items()):
        if decision.source != "package_generated":
            checks.append(
                ToolManufacturingCheck(
                    name=f"{tool_id}.source_decision",
                    status="passed",
                    message=f"Tool uses existing {decision.source} capability.",
                )
            )
            continue
        if tool_id in approved_by_id:
            approved.append(approved_by_id[tool_id])
            checks.append(
                ToolManufacturingCheck(
                    name=f"{tool_id}.approved_package_artifact",
                    status="passed",
                    message="package-generated tool already passed manufacturing pipeline",
                )
            )
            continue
        if tool_id in blocked_set:
            continue
        tool_checks, artifact = run_generated_tool_pipeline(
            factory_run_id=factory_run_id,
            tool_id=tool_id,
            design=designs_by_id.get(tool_id),
            spec=specs_by_id.get(tool_id),
            implementation=impls_by_id.get(tool_id),
            trial_plan=trials_by_id.get(tool_id),
            resource_facts=resource_facts or {},
            test_env_root=test_env_root,
        )
        checks.extend(tool_checks)
        if artifact is None:
            blocked_tool_ids = _append_unique(blocked_tool_ids, tool_id)
            continue
        approved.append(artifact)

    status = "valid" if not blocked_tool_ids else "invalid"
    generated_ids = {item.tool_id for item in output.source_decisions if item.source == "package_generated"}
    approved_ids = {item.tool_id for item in approved}
    missing_approved = sorted(generated_ids.difference(approved_ids).difference(blocked_tool_ids))
    if missing_approved:
        blocked_tool_ids = _append_many_unique(blocked_tool_ids, missing_approved)
        checks.append(
            ToolManufacturingCheck(
                name="approved_package_tools",
                status="failed",
                message="package_generated tools did not produce approved artifacts: " + ", ".join(missing_approved),
            )
        )
        status = "invalid"
    report = ToolManufacturingReport(
        status=status,
        source_decisions=output.source_decisions,
        checks=checks,
        approved_tool_ids=[item.tool_id for item in approved],
        blocked_tool_ids=_unique_strings(blocked_tool_ids),
        errors=unique_tool_manufacturing_errors(checks) if status != "valid" else [],
        warnings=list(output.report.warnings),
    )
    return output.model_copy(
        update={
            "approved_package_tools": approved,
            "inherited_extensions": inherited_extensions,
            "report": report,
        },
        deep=True,
    )


def run_generated_tool_pipeline(
    *,
    factory_run_id: str,
    tool_id: str,
    design: ToolDesign | None,
    spec: ToolSpecDraft | None,
    implementation: ToolImplementationDraft | None,
    trial_plan: ToolTrialPlan | None,
    resource_facts: dict[str, Any] | None = None,
    test_env_root: Path = TOOL_TEST_ENV_ROOT,
) -> tuple[list[ToolManufacturingCheck], ApprovedPackageToolArtifact | None]:
    checks = _run_generated_tool_pipeline(
        factory_run_id=factory_run_id,
        tool_id=tool_id,
        design=design,
        spec=spec,
        implementation=implementation,
        trial_plan=trial_plan,
        resource_facts=resource_facts or {},
        test_env_root=test_env_root,
    )
    if any(item.status == "failed" for item in checks):
        return checks, None
    if design is None or spec is None or implementation is None:
        return checks, None
    return checks, ApprovedPackageToolArtifact(
        tool_id=tool_id,
        description=spec.description,
        input_schema=spec.input_schema,
        output_schema=spec.output_schema,
        resources=spec.resources,
        risk_level=spec.risk_level,
        concurrent=spec.concurrent,
        python_requirements=design.python_requirements,
        system_packages=design.system_packages,
        system_binaries=design.system_binaries,
        code=implementation.code,
        manufacturing_report_ref=TOOL_MANUFACTURING_REPORT_PATH,
    )


def validate_tool_manufacturing_output(
    *,
    output: ToolManufacturingOutput,
    capability_contract: CapabilityContractOutput,
) -> list[str]:
    errors: list[str] = []
    expected = {item.tool_id: item for item in capability_contract.tool_specs_to_generate}
    decisions = {item.tool_id: item for item in output.source_decisions}
    missing_decisions = sorted(set(expected).difference(decisions))
    if missing_decisions:
        errors.append("tool manufacturing missing source decisions: " + ", ".join(missing_decisions))
    unknown_decisions = sorted(set(decisions).difference(expected))
    if unknown_decisions:
        errors.append("tool manufacturing emitted unknown tools: " + ", ".join(unknown_decisions))
    generated_ids = {item.tool_id for item in output.source_decisions if item.source == "package_generated"}
    non_generated_ids = {item.tool_id for item in output.source_decisions if item.source != "package_generated"}
    artifact_sets = {
        "ToolDesign": {item.tool_id for item in output.tool_designs},
        "ToolSpecDraft": {item.tool_id for item in output.tool_specs},
        "ToolImplementationDraft": {item.tool_id for item in output.implementations},
        "ToolTrialPlan": {item.tool_id for item in output.trial_plans},
        "ApprovedPackageToolArtifact": {item.tool_id for item in output.approved_package_tools},
    }
    for artifact_name, tool_ids in artifact_sets.items():
        extra = sorted(tool_ids.intersection(non_generated_ids))
        if extra:
            errors.append(f"{artifact_name} is only allowed for package_generated tools: " + ", ".join(extra))
        unknown = sorted(tool_ids.difference(generated_ids).difference(non_generated_ids))
        if unknown:
            errors.append(f"{artifact_name} references tools without a source decision: " + ", ".join(unknown))
    required_artifacts = {
        "ToolDesign": artifact_sets["ToolDesign"],
        "ToolSpecDraft": artifact_sets["ToolSpecDraft"],
        "ToolImplementationDraft": artifact_sets["ToolImplementationDraft"],
        "ToolTrialPlan": artifact_sets["ToolTrialPlan"],
    }
    for tool_id in sorted(generated_ids):
        missing = [artifact_name for artifact_name, tool_ids in required_artifacts.items() if tool_id not in tool_ids]
        if missing:
            errors.append(f"package_generated tool {tool_id} is missing manufacturing artifacts: " + ", ".join(missing))
    unknown_approved = sorted(artifact_sets["ApprovedPackageToolArtifact"].difference(generated_ids))
    if unknown_approved:
        errors.append("approved package tools must come from package_generated decisions: " + ", ".join(unknown_approved))
    for decision in output.source_decisions:
        for inherited in decision.inherited_extensions:
            if inherited.source != decision.source:
                errors.append(
                    f"{decision.tool_id} declares {inherited.source}:{inherited.extension_id} "
                    f"but source is {decision.source}"
                )
        if decision.source in {"mcp", "skill"} and not decision.inherited_extensions:
            errors.append(f"{decision.tool_id} uses {decision.source} but does not declare inherited_extensions")
        if decision.source not in {"mcp", "skill"} and decision.inherited_extensions:
            errors.append(f"{decision.tool_id} declares inherited_extensions but source is {decision.source}")
    return errors


def tool_manufacturing_message(output: ToolManufacturingOutput) -> str:
    report = output.report
    lines = [
        "Tool Manufacturing 已完成。" if report.status == "valid" else "Tool Manufacturing 未通过制造校验。",
        "",
        f"状态：{report.status}",
        f"工具来源决策：{len(output.source_decisions)} 个",
        f"已批准 package 工具：{len(output.approved_package_tools)} 个",
    ]
    if report.blocked_tool_ids:
        lines.extend(["", "阻塞工具：", *[f"- {item}" for item in report.blocked_tool_ids]])
    if report.errors:
        lines.extend(["", "错误：", *[f"- {item}" for item in report.errors]])
    if output.manufacturing_summary_text:
        lines.extend(["", "制造说明：", output.manufacturing_summary_text])
    return "\n".join(lines).strip()


def persist_tool_manufacturing_report(
    *,
    factory_run_id: str,
    output: ToolManufacturingOutput,
    artifact_root: Path = TOOL_MANUFACTURING_ARTIFACT_ROOT,
) -> dict[str, str]:
    run_id = _safe_path_id(factory_run_id or "unknown_run")
    report_root = (Path.cwd() / artifact_root / run_id / "reports").resolve()
    report_root.mkdir(parents=True, exist_ok=True)
    paths = {
        "tool_manufacturing_report": report_root / Path(TOOL_MANUFACTURING_REPORT_PATH).name,
        "tool_contract_smoke_report": report_root / Path(TOOL_CONTRACT_SMOKE_REPORT_PATH).name,
        "tool_resource_probe_report": report_root / Path(TOOL_RESOURCE_PROBE_REPORT_PATH).name,
        "tool_model_trial_report": report_root / Path(TOOL_MODEL_TRIAL_REPORT_PATH).name,
        "dependency_install_report": report_root / Path(TOOL_DEPENDENCY_REPORT_PATH).name,
    }
    paths["tool_manufacturing_report"].write_text(
        json.dumps(output.report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    checks_payload = [item.model_dump(mode="json") for item in output.report.checks]
    paths["tool_contract_smoke_report"].write_text(
        json.dumps(
            [item for item in checks_payload if str(item.get("name") or "").endswith(".contract_smoke")],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    paths["tool_model_trial_report"].write_text(
        json.dumps(
            [item for item in checks_payload if str(item.get("name") or "").endswith(".model_trial")],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    paths["tool_resource_probe_report"].write_text(
        json.dumps(
            [item for item in checks_payload if str(item.get("name") or "").endswith(".resource_probe")],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    paths["dependency_install_report"].write_text(
        json.dumps(
            [item for item in checks_payload if str(item.get("name") or "").endswith(".dependency_convergence")],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {key: str(path) for key, path in paths.items()}


def approved_package_tool_plans(output: ToolManufacturingOutput | None) -> list[PackageToolBuildPlan]:
    if output is None:
        return []
    return [
        PackageToolBuildPlan.model_validate(item.model_dump(mode="json", exclude={"manufacturing_status", "manufacturing_report_ref"}))
        for item in output.approved_package_tools
    ]


def tool_manufacturing_needs_external_input(report: ToolManufacturingReport | None) -> bool:
    return bool(tool_manufacturing_external_questions(report))


def tool_manufacturing_external_questions(report: ToolManufacturingReport | None) -> list[str]:
    if report is None:
        return []
    questions: list[str] = []
    seen: set[str] = set()
    for check in report.checks:
        summary = check.failure_summary
        if summary is None or summary.category not in _RESOURCE_FAILURE_CATEGORIES:
            continue
        tool_id = summary.tool_id
        if summary.category == "unprovenanced_external_source":
            question = (
                f"{tool_id} 需要外部来源，但生成结果包含未由你提供或继承的地址。"
                "请提供你希望它使用的真实来源，或明确暂不提供。"
            )
        else:
            question = (
                f"{tool_id} 的外部资源连通性未通过。"
                "请提供替代来源、账号或配置，或明确暂不提供。"
            )
        if question not in seen:
            questions.append(question)
            seen.add(question)
    return questions[:4]


def resolve_inherited_extensions(decisions: list[ToolSourceDecision]) -> list[InheritedExtensionArtifact]:
    refs: list[ToolInheritedExtensionRef] = []
    seen: set[tuple[str, str]] = set()
    for decision in decisions:
        for ref in decision.inherited_extensions:
            key = (ref.source, ref.extension_id)
            if key not in seen:
                refs.append(ref)
                seen.add(key)
    if not refs:
        return []
    catalog = _extension_inventory()
    artifacts: list[InheritedExtensionArtifact] = []
    for ref in refs:
        key = (ref.source, ref.extension_id)
        artifact = catalog.get(key)
        if artifact is None:
            raise ToolManufacturingError(f"inherited extension not found: {ref.source}:{ref.extension_id}")
        artifacts.append(artifact)
    return artifacts


def _run_generated_tool_pipeline(
    *,
    factory_run_id: str,
    tool_id: str,
    design: ToolDesign | None,
    spec: ToolSpecDraft | None,
    implementation: ToolImplementationDraft | None,
    trial_plan: ToolTrialPlan | None,
    resource_facts: dict[str, Any],
    test_env_root: Path,
) -> list[ToolManufacturingCheck]:
    checks: list[ToolManufacturingCheck] = []
    if design is None or spec is None or implementation is None or trial_plan is None:
        missing = [
            name
            for name, value in {
                "ToolDesign": design,
                "ToolSpecDraft": spec,
                "ToolImplementationDraft": implementation,
                "ToolTrialPlan": trial_plan,
            }.items()
            if value is None
        ]
        return [
            _failed_check(
                tool_id=tool_id,
                phase="required_artifacts",
                category="missing_manufacturing_artifact",
                primary_error="missing manufacturing artifacts: " + ", ".join(missing),
                suggested_action="Regenerate all required manufacturing artifacts for this package-generated tool.",
            )
        ]
    if not (design.tool_id == spec.tool_id == implementation.tool_id == trial_plan.tool_id == tool_id):
        return [
            _failed_check(
                tool_id=tool_id,
                phase="artifact_ids",
                category="artifact_identity_mismatch",
                primary_error="manufacturing artifact tool_id fields must all match the source decision",
                suggested_action="Regenerate tool artifacts with the same tool_id as the source decision.",
            )
        ]

    run_root = _prepare_test_run_root(test_env_root=test_env_root, factory_run_id=factory_run_id, tool_id=tool_id)
    package_root = run_root / "package"
    tool_root = package_root / "tools" / tool_id
    tool_root.mkdir(parents=True, exist_ok=True)
    (tool_root / "tool.py").write_text(implementation.code, encoding="utf-8")
    tool_spec = _tool_spec(spec)
    (tool_root / "manifest.json").write_text(
        json.dumps(tool_spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    checks.append(_check_python_compile(tool_root / "tool.py", tool_id=tool_id))
    checks.append(_check_entrypoint_signature(tool_root / "tool.py", tool_id=tool_id))
    checks.append(_check_tool_spec(tool_spec, tool_id=tool_id))
    checks.append(
        _check_external_source_provenance(
            code=implementation.code,
            tool_id=tool_id,
        )
    )
    checks.append(
        _check_trial_external_resource_provenance(
            trial_plan=trial_plan,
            tool_id=tool_id,
            resource_facts=resource_facts,
        )
    )
    if any(item.status == "failed" for item in checks):
        return checks
    checks.extend(_converge_test_environment(
        test_env_root=test_env_root,
        requirements=design.python_requirements,
        tool_id=tool_id,
    ))
    if any(item.status == "failed" for item in checks):
        return checks
    import_paths = _venv_import_paths((Path.cwd() / test_env_root).resolve())
    with _temporary_sys_path(import_paths):
        checks.append(_run_contract_smoke(package_root=package_root, spec=tool_spec, trial_plan=trial_plan, tool_id=tool_id))
        if checks[-1].status == "failed":
            return checks
        checks.append(
            _run_resource_probe(
                package_root=package_root,
                spec=tool_spec,
                trial_plan=trial_plan,
                tool_id=tool_id,
            )
        )
        if checks[-1].status == "failed":
            return checks
        checks.append(_run_model_trial(package_root=package_root, spec=tool_spec, trial_plan=trial_plan, tool_id=tool_id))
    return checks


def _inheritable_extension_catalog() -> dict[str, Any]:
    inventory = _extension_inventory()
    mcp_servers = []
    skills = []
    for (source, extension_id), artifact in sorted(inventory.items()):
        if source == "mcp":
            mcp_servers.append(
                {
                    "server_id": extension_id,
                    "enabled": bool(artifact.config.get("enabled", True)),
                    "transport": artifact.config.get("transport"),
                    "tool_id_prefix": artifact.config.get("tool_id_prefix"),
                    "source_path": artifact.source_path,
                }
            )
        elif source == "skill":
            skills.append(
                {
                    "skill_id": extension_id,
                    "enabled": bool(artifact.config.get("enabled", True)),
                    "path": artifact.config.get("path"),
                    "source_path": artifact.source_path,
                }
            )
    return {"mcp_servers": mcp_servers, "skills": skills}


def _extension_inventory() -> dict[tuple[str, str], InheritedExtensionArtifact]:
    inventory: dict[tuple[str, str], InheritedExtensionArtifact] = {}
    for root in _factory_extension_roots():
        _load_mcp_extensions(root, inventory)
        _load_skill_extensions(root, inventory)
    return inventory


def _factory_extension_roots() -> list[Path]:
    roots: list[Path] = []
    for root in [default_factory_extension_root(), project_root() / SYSTEM_PACKAGE_EXTENSION_ROOT]:
        resolved = root.expanduser().resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _load_mcp_extensions(root: Path, inventory: dict[tuple[str, str], InheritedExtensionArtifact]) -> None:
    path = root / "mcp_servers.json"
    payload = _read_json_object(path)
    servers = payload.get("servers") if isinstance(payload, dict) else None
    if not isinstance(servers, list):
        return
    for item in servers:
        if not isinstance(item, dict):
            continue
        server_id = str(item.get("server_id") or "").strip()
        if not server_id:
            continue
        if not bool(item.get("enabled", True)):
            continue
        inventory.setdefault(
            ("mcp", server_id),
            InheritedExtensionArtifact(
                source="mcp",
                extension_id=server_id,
                config=dict(item),
                source_path=str(path),
                target_path="extensions/mcp_servers.json",
            ),
        )


def _load_skill_extensions(root: Path, inventory: dict[tuple[str, str], InheritedExtensionArtifact]) -> None:
    path = root / "enabled_skills.json"
    payload = _read_json_object(path)
    skills = payload.get("skills") if isinstance(payload, dict) else None
    if not isinstance(skills, list):
        return
    for item in skills:
        if not isinstance(item, dict):
            continue
        skill_id = str(item.get("skill_id") or "").strip()
        skill_path = str(item.get("path") or "").strip()
        if not skill_id or not skill_path:
            continue
        if not bool(item.get("enabled", True)):
            continue
        source_path = Path(skill_path).expanduser()
        if not source_path.is_absolute():
            source_path = root / source_path
        source_path = source_path.resolve()
        inventory.setdefault(
            ("skill", skill_id),
            InheritedExtensionArtifact(
                source="skill",
                extension_id=skill_id,
                config={**dict(item), "path": f"skills/{skill_id}"},
                source_path=str(source_path),
                target_path=f"extensions/skills/{skill_id}",
            ),
        )


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _tool_spec(spec: ToolSpecDraft) -> ToolSpec:
    return ToolSpec(
        id=spec.tool_id,
        description=spec.description,
        entrypoint=f"tools/{spec.tool_id}/tool.py:run",
        input_schema=spec.input_schema,
        output_schema=spec.output_schema,
        resources=spec.resources,
        risk_level=spec.risk_level,
        risk_evaluator=ToolRiskEvaluatorConfig(llm_mode="disabled"),
        concurrent=spec.concurrent,
    )


def _prepare_test_run_root(*, test_env_root: Path, factory_run_id: str, tool_id: str) -> Path:
    safe_run_id = _safe_path_id(factory_run_id or "unknown_run")
    safe_tool_id = _safe_path_id(tool_id)
    run_root = (Path.cwd() / test_env_root / "test_runs" / safe_run_id / safe_tool_id).resolve()
    if run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    return run_root


def _check_python_compile(path: Path, *, tool_id: str) -> ToolManufacturingCheck:
    try:
        py_compile.compile(str(path), doraise=True)
        return ToolManufacturingCheck(name=f"{tool_id}.python_compile", status="passed")
    except Exception as exc:
        return _failed_check(
            tool_id=tool_id,
            phase="python_compile",
            category="implementation_syntax_error",
            primary_error=f"{type(exc).__name__}: {exc}",
            suggested_action="Regenerate tool.py so it is syntactically valid Python.",
        )


def _check_entrypoint_signature(path: Path, *, tool_id: str) -> ToolManufacturingCheck:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        run_fn = next((node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "run"), None)
        if run_fn is None:
            raise ValueError("tool.py must define run")
        args = [item.arg for item in run_fn.args.args]
        if args[:2] != ["arguments", "resources"]:
            raise ValueError("run signature must start with arguments, resources")
        return ToolManufacturingCheck(name=f"{tool_id}.entrypoint_signature", status="passed")
    except Exception as exc:
        return _failed_check(
            tool_id=tool_id,
            phase="entrypoint_signature",
            category="implementation_entrypoint_error",
            primary_error=f"{type(exc).__name__}: {exc}",
            suggested_action="Regenerate tool.py with def run(arguments: dict, resources: dict) -> dict.",
        )


def _check_tool_spec(spec: ToolSpec, *, tool_id: str) -> ToolManufacturingCheck:
    try:
        ToolSpec.model_validate(spec.model_dump(mode="json"))
        return ToolManufacturingCheck(name=f"{tool_id}.tool_spec", status="passed")
    except Exception as exc:
        return _failed_check(
            tool_id=tool_id,
            phase="tool_spec",
            category="tool_spec_schema_error",
            primary_error=f"{type(exc).__name__}: {exc}",
            suggested_action="Regenerate ToolSpecDraft so the manifest matches the runtime ToolSpec schema.",
        )


def _check_external_source_provenance(
    *,
    code: str,
    tool_id: str,
) -> ToolManufacturingCheck:
    hardcoded_hosts = sorted(_external_hosts_from_code(code))
    if not hardcoded_hosts:
        return ToolManufacturingCheck(
            name=f"{tool_id}.external_source_provenance",
            status="passed",
            message="implementation does not hard-code external hosts",
        )
    return _failed_check(
        tool_id=tool_id,
        phase="resource_probe",
        category="unprovenanced_external_source",
        primary_error=(
            "implementation hard-codes external host(s) instead of reading them from resources: "
            + ", ".join(hardcoded_hosts)
        ),
        suggested_action=(
            "Remove hard-coded external hosts. Read endpoints, URLs, accounts, and tokens from ToolSpec resources "
            "or ask the user for the resource before manufacturing the tool."
        ),
    )


def _check_trial_external_resource_provenance(
    *,
    trial_plan: ToolTrialPlan,
    tool_id: str,
    resource_facts: dict[str, Any],
) -> ToolManufacturingCheck:
    scenario_hosts = sorted(
        {
            host
            for scenario in trial_plan.scenarios
            for host in _external_hosts_from_value({"arguments": scenario.arguments, "resources": scenario.resources})
        }
    )
    if not scenario_hosts:
        return ToolManufacturingCheck(
            name=f"{tool_id}.trial_external_source_provenance",
            status="passed",
            message="trial scenarios do not include explicit external hosts",
        )
    allowed_hosts = _external_hosts_from_value(resource_facts)
    unknown_hosts = [host for host in scenario_hosts if host not in allowed_hosts]
    if not unknown_hosts:
        return ToolManufacturingCheck(
            name=f"{tool_id}.trial_external_source_provenance",
            status="passed",
            message="trial scenario external hosts are present in confirmed resource facts",
            details={"hosts": scenario_hosts},
        )
    return _failed_check(
        tool_id=tool_id,
        phase="resource_probe",
        category="unprovenanced_external_source",
        primary_error=(
            "trial scenarios use external host(s) without user, inherited extension, or system provenance: "
            + ", ".join(unknown_hosts)
        ),
        suggested_action=(
            "Do not invent trial URLs or endpoints. Ask the user for the real external resource, "
            "or remove external values from manufacturing trials."
        ),
    )


def _external_hosts_from_code(code: str) -> set[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    hosts: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            hosts.update(_external_hosts_from_text(node.value))
    return hosts


def _external_hosts_from_value(value: Any) -> set[str]:
    hosts: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            hosts.update(_external_hosts_from_value(item))
    elif isinstance(value, list):
        for item in value:
            hosts.update(_external_hosts_from_value(item))
    elif isinstance(value, str):
        hosts.update(_external_hosts_from_text(value))
    return hosts


def _external_hosts_from_text(text: str) -> set[str]:
    hosts: set[str] = set()
    for match in _EXTERNAL_HOST_PATTERN.finditer(text):
        host = match.group(1).lower().strip(".")
        if host:
            hosts.add(host)
    return hosts


def _has_external_value(value: Any) -> bool:
    return bool(_external_hosts_from_value(value))


def _resource_probe_failure_reason(*, observation: dict[str, Any], output: Any) -> str:
    status = str(observation.get("status") or "")
    if status and status != "completed":
        return str(observation.get("message") or status)
    if not isinstance(output, dict):
        return ""
    business_status = str(output.get("status") or output.get("state") or "").strip().lower()
    if business_status in {"error", "failed", "failure", "unavailable"}:
        return str(output.get("error") or output.get("message") or business_status)
    for key in ("error", "errors"):
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value:
            return "; ".join(str(item) for item in value[:3])
    return ""


def _run_contract_smoke(
    *,
    package_root: Path,
    spec: ToolSpec,
    trial_plan: ToolTrialPlan,
    tool_id: str,
) -> ToolManufacturingCheck:
    report_path = package_root.parent / Path(TOOL_CONTRACT_SMOKE_REPORT_PATH).name
    scenario_reports: list[dict[str, Any]] = []
    try:
        if not trial_plan.scenarios:
            raise ToolManufacturingError("ToolTrialPlan must include at least one scenario")
        safe_scenarios = [
            scenario
            for scenario in trial_plan.scenarios
            if not _has_external_value(scenario.arguments) and not _has_external_value(scenario.resources)
        ]
        if not safe_scenarios:
            compiler = ToolCompiler(
                package_root=package_root,
                resources={},
                approval_handler=lambda _spec, _arguments, _risk: ToolApprovalDecision(action="approve"),
            )
            tool = compiler.compile(spec)
            observation = _normalize_tool_observation(tool.invoke({}))
            status = str(observation.get("status") or "")
            if status not in {"completed", "invalid_arguments"}:
                raise ToolManufacturingError(
                    "synthetic_contract_smoke: expected completed or invalid_arguments, "
                    f"got {status or '<empty>'}; {observation.get('message') or 'no observation message'}"
                )
            scenario_reports.append(
                {
                    "scenario_id": "synthetic_contract_smoke",
                    "observation_status": status,
                    "message": str(observation.get("message") or "")[:1000],
                    "errors": [str(item)[:1000] for item in list(observation.get("errors") or [])[:5]],
                    "resource_paths": [],
                    "output_keys": [],
                    "status": "passed",
                    "business_assertions": "not_evaluated_in_contract_smoke",
                }
            )
        for scenario in safe_scenarios:
            trial_resources = _trial_resources_for_spec(
                spec=spec,
                scenario_resources=scenario.resources,
                scenario_arguments=scenario.arguments,
            )
            compiler = ToolCompiler(
                package_root=package_root,
                resources=trial_resources,
                approval_handler=lambda _spec, _arguments, _risk: ToolApprovalDecision(action="approve"),
            )
            tool = compiler.compile(spec)
            observation = _normalize_tool_observation(tool.invoke(dict(scenario.arguments)))
            output = observation.get("output") or {}
            scenario_report = _contract_smoke_scenario_report(
                scenario_id=scenario.scenario_id,
                observation=observation,
                resources=trial_resources,
                output=output,
            )
            status = str(observation.get("status") or "")
            if status != scenario.expected_observation_status:
                scenario_reports.append({**scenario_report, "status": "failed"})
                raise ToolManufacturingError(
                    f"{scenario.scenario_id}: expected observation status "
                    f"{scenario.expected_observation_status}, got {status or '<empty>'}; "
                    f"{observation.get('message') or 'no observation message'}"
                )
            if scenario.expected_output_keys and not isinstance(output, dict):
                scenario_reports.append({**scenario_report, "status": "failed"})
                raise ToolManufacturingError(f"{scenario.scenario_id}: output must be an object")
            for key in scenario.expected_output_keys:
                if key not in output:
                    scenario_reports.append({**scenario_report, "status": "failed"})
                    raise ToolManufacturingError(f"{scenario.scenario_id}: output.{key} is missing")
            scenario_reports.append(
                {
                    **scenario_report,
                    "status": "passed",
                    "business_assertions": "not_evaluated_in_contract_smoke",
                }
            )
        report_path.write_text(
            json.dumps(
                {
                    "tool_id": tool_id,
                    "phase": "contract_smoke",
                    "status": "passed",
                    "scenarios": scenario_reports,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return ToolManufacturingCheck(
            name=f"{tool_id}.contract_smoke",
            status="passed",
            message="contract smoke passed through ToolCompiler and ToolExecutionGateway without business content assertions",
            details={
                "report_path": str(report_path),
                "scenario_count": len(safe_scenarios) if safe_scenarios else 1,
                "assertion_scope": "schema_and_gateway_only",
            },
        )
    except Exception as exc:
        primary_error = f"{type(exc).__name__}: {exc}"
        report_path.write_text(
            json.dumps(
                {
                    "tool_id": tool_id,
                    "phase": "contract_smoke",
                    "status": "failed",
                    "category": "contract_smoke_error",
                    "primary_error": primary_error,
                    "scenarios": scenario_reports,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return _failed_check(
            tool_id=tool_id,
            phase="contract_smoke",
            category="contract_smoke_error",
            primary_error=primary_error,
            report_path=report_path,
            suggested_action="Repair ToolSpec, resource selectors, or implementation so scenario arguments execute through ToolCompiler and Gateway.",
        )


def _run_resource_probe(
    *,
    package_root: Path,
    spec: ToolSpec,
    trial_plan: ToolTrialPlan,
    tool_id: str,
) -> ToolManufacturingCheck:
    report_path = package_root.parent / Path(TOOL_RESOURCE_PROBE_REPORT_PATH).name
    scenario_reports: list[dict[str, Any]] = []
    probe_scenarios = [
        scenario
        for scenario in trial_plan.scenarios
        if _has_external_value(scenario.arguments) or _has_external_value(scenario.resources)
    ]
    if not probe_scenarios:
        report_path.write_text(
            json.dumps(
                {
                    "tool_id": tool_id,
                    "phase": "resource_probe",
                    "status": "skipped",
                    "reason": "no explicit external resource values in trial scenarios",
                    "scenarios": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return ToolManufacturingCheck(
            name=f"{tool_id}.resource_probe",
            status="skipped",
            message="resource probe skipped because no explicit external resource values were supplied",
            details={"report_path": str(report_path), "scenario_count": 0},
        )
    try:
        for scenario in probe_scenarios:
            trial_resources = _trial_resources_for_spec(
                spec=spec,
                scenario_resources=scenario.resources,
                scenario_arguments=scenario.arguments,
            )
            compiler = ToolCompiler(
                package_root=package_root,
                resources=trial_resources,
                approval_handler=lambda _spec, _arguments, _risk: ToolApprovalDecision(action="approve"),
            )
            tool = compiler.compile(spec)
            observation = _normalize_tool_observation(tool.invoke(dict(scenario.arguments)))
            output = observation.get("output") or {}
            scenario_report = _contract_smoke_scenario_report(
                scenario_id=scenario.scenario_id,
                observation=observation,
                resources=trial_resources,
                output=output,
            )
            status = str(observation.get("status") or "")
            failure_reason = _resource_probe_failure_reason(observation=observation, output=output)
            if status != "completed" or failure_reason:
                scenario_reports.append({**scenario_report, "status": "failed", "failure_reason": failure_reason})
                raise ToolManufacturingError(
                    f"{scenario.scenario_id}: external resource probe failed: "
                    f"{failure_reason or observation.get('message') or status or 'unknown failure'}"
                )
            scenario_reports.append({**scenario_report, "status": "passed"})
        report_path.write_text(
            json.dumps(
                {
                    "tool_id": tool_id,
                    "phase": "resource_probe",
                    "status": "passed",
                    "scenarios": scenario_reports,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return ToolManufacturingCheck(
            name=f"{tool_id}.resource_probe",
            status="passed",
            message="user-provided external resources passed probe scenarios",
            details={"report_path": str(report_path), "scenario_count": len(probe_scenarios)},
        )
    except Exception as exc:
        primary_error = f"{type(exc).__name__}: {exc}"
        report_path.write_text(
            json.dumps(
                {
                    "tool_id": tool_id,
                    "phase": "resource_probe",
                    "status": "failed",
                    "category": "external_resource_unavailable",
                    "primary_error": primary_error,
                    "scenarios": scenario_reports,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return _failed_check(
            tool_id=tool_id,
            phase="resource_probe",
            category="external_resource_unavailable",
            primary_error=primary_error,
            report_path=report_path,
            suggested_action="Ask the user for a replacement endpoint, account, token, or explicit skip before manufacturing continues.",
        )


def _normalize_tool_observation(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except Exception as exc:
            raise ToolManufacturingError("tool observation string is not valid JSON") from exc
        if isinstance(payload, dict):
            return payload
    raise ToolManufacturingError(f"tool observation must be an object, got {type(value).__name__}")


def _trial_resources_for_spec(
    *,
    spec: ToolSpec,
    scenario_resources: dict[str, Any],
    scenario_arguments: dict[str, Any],
) -> dict[str, Any]:
    """Build the runtime resource tree expected by ToolSpec selectors.

    ToolTrialPlan is authored around a single tool, so models naturally provide
    local resource names such as ``news_sources``. Runtime execution resolves
    ToolSpec selectors such as ``report_config.news_sources``. This adapter is
    the stable boundary between those two representations.
    """

    resources = _deep_json_copy(scenario_resources)
    for local_name, selector in spec.resources.items():
        if _has_resource_path(resources, selector):
            continue
        if local_name in scenario_resources:
            _set_resource_path(resources, selector, scenario_resources[local_name])
            continue
        if local_name in scenario_arguments:
            _set_resource_path(resources, selector, scenario_arguments[local_name])
    return resources


def _contract_smoke_scenario_report(
    *,
    scenario_id: str,
    observation: dict[str, Any],
    resources: dict[str, Any],
    output: Any,
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "observation_status": str(observation.get("status") or ""),
        "message": str(observation.get("message") or "")[:1000],
        "errors": [str(item)[:1000] for item in list(observation.get("errors") or [])[:5]],
        "resource_paths": sorted(_flatten_resource_paths(resources)),
        "output_keys": sorted(output.keys()) if isinstance(output, dict) else [],
    }


def _deep_json_copy(value: dict[str, Any]) -> dict[str, Any]:
    try:
        copied = json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return dict(value)
    return copied if isinstance(copied, dict) else {}


def _has_resource_path(resources: dict[str, Any], selector: str) -> bool:
    current: Any = resources
    for part in selector.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _set_resource_path(resources: dict[str, Any], selector: str, value: Any) -> None:
    current: dict[str, Any] = resources
    parts = selector.split(".")
    for part in parts[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[parts[-1]] = value


def _flatten_resource_paths(resources: dict[str, Any], prefix: str = "") -> list[str]:
    paths: list[str] = []
    for key, value in resources.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            paths.extend(_flatten_resource_paths(value, path))
        else:
            paths.append(path)
    return paths


def _run_model_trial(
    *,
    package_root: Path,
    spec: ToolSpec,
    trial_plan: ToolTrialPlan,
    tool_id: str,
) -> ToolManufacturingCheck:
    report_path = package_root.parent / Path(TOOL_MODEL_TRIAL_REPORT_PATH).name
    scenario_reports: list[dict[str, Any]] = []
    try:
        task_model = get_task_model()
        if task_model is None:
            raise ToolManufacturingError("task model is not configured for model-bound tool trial")
        operation = ModelOperationService(role="task", model=task_model)
        for scenario in trial_plan.scenarios:
            trial_resources = _trial_resources_for_spec(
                spec=spec,
                scenario_resources=scenario.resources,
                scenario_arguments=scenario.arguments,
            )
            compiler = ToolCompiler(
                package_root=package_root,
                resources=trial_resources,
                approval_handler=lambda _spec, _arguments, _risk: ToolApprovalDecision(action="approve"),
            )
            tool = compiler.compile(spec)
            model_result = operation.tool_bound_chat(
                state=None,
                messages=[HumanMessage(content=scenario.user_prompt)],
                tools=[tool],
            )
            ai_message = model_result.ai_message
            if ai_message is None or not getattr(ai_message, "tool_calls", None):
                raise ToolManufacturingError(f"{scenario.scenario_id}: task model did not emit a tool call")
            _ai, tool_calls = latest_ai_tool_calls([ai_message])
            if not any(str(call.get("name") or "") == scenario.expected_tool_id for call in tool_calls):
                emitted = ", ".join(str(call.get("name") or "") for call in tool_calls)
                raise ToolManufacturingError(
                    f"{scenario.scenario_id}: task model emitted unexpected tool ids: {emitted or '<none>'}"
                )
            runner = build_tool_node_runner([tool], node_id="tool_manufacturing_model_trial")
            output = runner.invoke({"messages": [ai_message]})
            tool_messages = output.get("messages") or []
            results, failures, _policy, _route = tool_messages_to_runtime_patch(tool_messages)
            if failures:
                raise ToolManufacturingError(
                    f"{scenario.scenario_id}: "
                    + "; ".join(str(item.get("message") or item) for item in failures)
                )
            if not results:
                raise ToolManufacturingError(f"{scenario.scenario_id}: ToolNode did not return a completed observation")
            final = operation.tool_bound_chat(
                state=None,
                messages=[
                    HumanMessage(content=scenario.user_prompt),
                    ai_message if isinstance(ai_message, AIMessage) else AIMessage(content=""),
                    *tool_messages,
                ],
                tools=[tool],
            )
            final_text = str(final.final_answer or final.assistant_draft or "")
            if not final_text.strip():
                raise ToolManufacturingError(f"{scenario.scenario_id}: task model did not produce a final answer")
            for expected_text in scenario.expected_final_answer_contains:
                if expected_text not in final_text:
                    raise ToolManufacturingError(
                        f"{scenario.scenario_id}: final answer is missing expected text {expected_text!r}"
                    )
            scenario_reports.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "status": "passed",
                    "tool_call_count": len(tool_calls),
                    "final_answer_preview": final_text[:500],
                }
            )
        report_path.write_text(
            json.dumps(
                {
                    "tool_id": tool_id,
                    "phase": "model_trial",
                    "status": "passed",
                    "scenarios": scenario_reports,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return ToolManufacturingCheck(
            name=f"{tool_id}.model_trial",
            status="passed",
            message="model-bound trial passed through task model, ToolNode, Gateway, ToolMessage, and final answer",
            details={"report_path": str(report_path), "scenario_count": len(trial_plan.scenarios)},
        )
    except Exception as exc:
        primary_error = f"{type(exc).__name__}: {exc}"
        report_path.write_text(
            json.dumps(
                {
                    "tool_id": tool_id,
                    "phase": "model_trial",
                    "status": "failed",
                    "category": "model_trial_error",
                    "primary_error": primary_error,
                    "scenarios": scenario_reports,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return _failed_check(
            tool_id=tool_id,
            phase="model_trial",
            category="model_trial_error",
            primary_error=primary_error,
            report_path=report_path,
            suggested_action="Repair tool name, description, schema, implementation, or trial prompt so the task model can call the tool and answer from the observation.",
        )


def _converge_test_environment(
    *,
    test_env_root: Path,
    requirements: list[str],
    tool_id: str,
) -> list[ToolManufacturingCheck]:
    root = (Path.cwd() / test_env_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    report_path = root / "install_reports" / f"{tool_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with _tool_test_env_lock(root):
        venv_python = _ensure_venv(root / "venv")
        clean_requirements = _dedupe_requirements(requirements)
        started = perf_counter()
        if clean_requirements:
            command = [str(venv_python), "-m", "pip", "install", *clean_requirements]
            result = subprocess.run(command, cwd=str(root), capture_output=True, text=True, timeout=600)
        else:
            command = [str(venv_python), "-m", "pip", "list", "--format=json"]
            result = subprocess.run(command, cwd=str(root), capture_output=True, text=True, timeout=120)
        duration_ms = int((perf_counter() - started) * 1000)
        report = {
            "tool_id": tool_id,
            "requirements": clean_requirements,
            "command": command,
            "returncode": result.returncode,
            "duration_ms": duration_ms,
            "category": "dependency_install_error" if result.returncode != 0 else "",
            "primary_error": _extract_primary_error(result.stdout, result.stderr) if result.returncode != 0 else "",
            "stdout_preview": result.stdout[-4000:],
            "stderr_preview": result.stderr[-4000:],
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if result.returncode != 0:
            return [
                _failed_check(
                    tool_id=tool_id,
                    phase="dependency_convergence",
                    category="dependency_install_error",
                    primary_error=_extract_primary_error(result.stdout, result.stderr) or "dependency convergence failed",
                    report_path=report_path,
                    suggested_action="Regenerate dependency declarations or remove unavailable packages from ToolDesign.python_requirements.",
                    details={"returncode": result.returncode},
                )
            ]
        return [
            ToolManufacturingCheck(
                name=f"{tool_id}.dependency_convergence",
                status="passed",
                message="dependency environment converged",
                details={"report_path": str(report_path), "duration_ms": duration_ms},
            )
        ]


def _failed_check(
    *,
    tool_id: str,
    phase: str,
    category: str,
    primary_error: str,
    suggested_action: str,
    report_path: Path | str | None = None,
    details: dict[str, Any] | None = None,
) -> ToolManufacturingCheck:
    report_path_text = str(report_path or "")
    summary = ToolManufacturingFailureSummary(
        tool_id=tool_id,
        phase=phase,  # type: ignore[arg-type]
        category=category,
        primary_error=primary_error,
        report_path=report_path_text,
        suggested_action=suggested_action,
    )
    payload = dict(details or {})
    if report_path_text:
        payload.setdefault("report_path", report_path_text)
    payload.setdefault("category", category)
    payload.setdefault("primary_error", primary_error)
    if suggested_action:
        payload.setdefault("suggested_action", suggested_action)
    return ToolManufacturingCheck(
        name=f"{tool_id}.{phase}",
        status="failed",
        message=_format_failure_summary(summary),
        details=payload,
        failure_summary=summary,
    )


def _check_error_text(check: ToolManufacturingCheck) -> str:
    if check.failure_summary is not None:
        return _format_failure_summary(check.failure_summary)
    return check.message or check.name


def unique_tool_manufacturing_errors(checks: list[ToolManufacturingCheck]) -> list[str]:
    return _unique_strings([_check_error_text(item) for item in checks if item.status == "failed"])


def _format_failure_summary(summary: ToolManufacturingFailureSummary) -> str:
    text = f"{summary.tool_id}/{summary.phase}[{summary.category}]: {summary.primary_error}"
    if summary.report_path:
        text += f" (report: {summary.report_path})"
    if summary.suggested_action:
        text += f" | suggested_action: {summary.suggested_action}"
    return text


def _extract_primary_error(stdout: str, stderr: str) -> str:
    text = "\n".join(part for part in [stdout, stderr] if part)
    lines = [line.rstrip() for line in text.splitlines()]
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("E   "):
            return stripped[4:].strip()
    for line in lines:
        stripped = line.strip()
        if any(marker in stripped for marker in ["ModuleNotFoundError:", "ImportError:", "AssertionError", "ValidationError:", "TypeError:", "ValueError:"]):
            return stripped
    for line in lines:
        stripped = line.strip()
        if stripped:
            return stripped[:500]
    return ""


def _append_unique(values: list[str], value: str) -> list[str]:
    return _append_many_unique(values, [value])


def _append_many_unique(values: list[str], additions: list[str]) -> list[str]:
    return _unique_strings([*values, *additions])


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _venv_import_paths(test_env_root: Path) -> list[str]:
    venv_python = _venv_python(test_env_root / "venv")
    if not venv_python.exists():
        return []
    script = (
        "import json, site\n"
        "paths = []\n"
        "for value in site.getsitepackages():\n"
        "    paths.append(value)\n"
        "user = site.getusersitepackages()\n"
        "if user:\n"
        "    paths.append(user)\n"
        "print(json.dumps(paths))\n"
    )
    try:
        result = subprocess.run([str(venv_python), "-c", script], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return []
        payload = json.loads(result.stdout.strip() or "[]")
    except Exception:
        return []
    return [str(item) for item in payload if isinstance(item, str) and item]


@contextmanager
def _temporary_sys_path(paths: list[str]) -> Iterator[None]:
    original = list(sys.path)
    for path in reversed(paths):
        if path and path not in sys.path:
            sys.path.insert(0, path)
    try:
        yield
    finally:
        sys.path[:] = original


def _ensure_venv(venv_root: Path) -> Path:
    python_path = _venv_python(venv_root)
    if python_path.exists():
        return python_path
    subprocess.run([sys.executable, "-m", "venv", str(venv_root)], check=True, capture_output=True, text=True, timeout=300)
    return python_path


def _venv_python(venv_root: Path) -> Path:
    if os.name == "nt":
        return venv_root / "Scripts" / "python.exe"
    return venv_root / "bin" / "python"


@contextmanager
def _tool_test_env_lock(root: Path) -> Iterator[None]:
    lock_path = root / ".lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("w", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        handle.close()


def _dedupe_requirements(requirements: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in requirements:
        item = str(raw).strip()
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _safe_path_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value).strip().lower())
    return cleaned.strip("_") or "item"
