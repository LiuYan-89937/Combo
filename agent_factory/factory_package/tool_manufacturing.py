from __future__ import annotations

import ast
from contextlib import contextmanager
import json
import os
from pathlib import Path
import py_compile
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
    ToolBindingSmokePlan,
    ToolDesign,
    ToolInheritedExtensionRef,
    ToolImplementationDraft,
    ToolManufacturingCheck,
    ToolManufacturingFailureSummary,
    ToolManufacturingOutput,
    ToolManufacturingReport,
    ToolSourceDecision,
    ToolSpecDraft,
    ToolUnitTestPlan,
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
TOOL_TEST_REPORT_PATH = "reports/tool_test_report.json"
TOOL_BINDING_SMOKE_REPORT_PATH = "reports/tool_binding_smoke_report.json"
TOOL_DEPENDENCY_REPORT_PATH = "reports/dependency_install_report.json"
TOOL_TEST_ENV_ROOT = Path(".agentfactory/tool_test_env")
TOOL_MANUFACTURING_ARTIFACT_ROOT = Path(".agentfactory/tool_manufacturing")
SYSTEM_PACKAGE_EXTENSION_ROOT = Path("SystemPackage/extensions")


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
    test_env_root: Path = TOOL_TEST_ENV_ROOT,
) -> ToolManufacturingOutput:
    errors = validate_tool_manufacturing_output(output=output, capability_contract=capability_contract)
    checks: list[ToolManufacturingCheck] = list(output.report.checks)
    approved: list[ApprovedPackageToolArtifact] = []
    blocked_tool_ids: list[str] = list(output.report.blocked_tool_ids)
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
    tests_by_id = {item.tool_id: item for item in output.unit_tests}
    smokes_by_id = {item.tool_id: item for item in output.binding_smokes}
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
            unit_test=tests_by_id.get(tool_id),
            binding_smoke=smokes_by_id.get(tool_id),
            test_env_root=test_env_root,
        )
        checks.extend(tool_checks)
        if artifact is None:
            blocked_tool_ids.append(tool_id)
            continue
        approved.append(artifact)

    status = "valid" if not blocked_tool_ids else "invalid"
    generated_ids = {item.tool_id for item in output.source_decisions if item.source == "package_generated"}
    approved_ids = {item.tool_id for item in approved}
    missing_approved = sorted(generated_ids.difference(approved_ids).difference(blocked_tool_ids))
    if missing_approved:
        blocked_tool_ids.extend(missing_approved)
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
        blocked_tool_ids=blocked_tool_ids,
        errors=[_check_error_text(item) for item in checks if item.status == "failed"] if status != "valid" else [],
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
    unit_test: ToolUnitTestPlan | None,
    binding_smoke: ToolBindingSmokePlan | None,
    test_env_root: Path = TOOL_TEST_ENV_ROOT,
) -> tuple[list[ToolManufacturingCheck], ApprovedPackageToolArtifact | None]:
    checks = _run_generated_tool_pipeline(
        factory_run_id=factory_run_id,
        tool_id=tool_id,
        design=design,
        spec=spec,
        implementation=implementation,
        unit_test=unit_test,
        binding_smoke=binding_smoke,
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
        "ToolUnitTestPlan": {item.tool_id for item in output.unit_tests},
        "ToolBindingSmokePlan": {item.tool_id for item in output.binding_smokes},
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
        "ToolUnitTestPlan": artifact_sets["ToolUnitTestPlan"],
        "ToolBindingSmokePlan": artifact_sets["ToolBindingSmokePlan"],
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
        "tool_manufacturing_report": report_root / "tool_manufacturing_report.json",
        "tool_test_report": report_root / "tool_test_report.json",
        "tool_binding_smoke_report": report_root / "tool_binding_smoke_report.json",
        "dependency_install_report": report_root / "dependency_install_report.json",
    }
    paths["tool_manufacturing_report"].write_text(
        json.dumps(output.report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    checks_payload = [item.model_dump(mode="json") for item in output.report.checks]
    paths["tool_test_report"].write_text(
        json.dumps(
            [
                item
                for item in checks_payload
                if str(item.get("name") or "").endswith(".unit_test_harness")
                or str(item.get("name") or "").endswith(".unit_tests")
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    paths["tool_binding_smoke_report"].write_text(
        json.dumps(
            [item for item in checks_payload if str(item.get("name") or "").endswith(".binding_smoke")],
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
    unit_test: ToolUnitTestPlan | None,
    binding_smoke: ToolBindingSmokePlan | None,
    test_env_root: Path,
) -> list[ToolManufacturingCheck]:
    checks: list[ToolManufacturingCheck] = []
    if design is None or spec is None or implementation is None or unit_test is None or binding_smoke is None:
        missing = [
            name
            for name, value in {
                "ToolDesign": design,
                "ToolSpecDraft": spec,
                "ToolImplementationDraft": implementation,
                "ToolUnitTestPlan": unit_test,
                "ToolBindingSmokePlan": binding_smoke,
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
    if not (design.tool_id == spec.tool_id == implementation.tool_id == unit_test.tool_id == binding_smoke.tool_id == tool_id):
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
    test_root = run_root / "tests"
    test_root.mkdir(parents=True, exist_ok=True)
    (test_root / f"test_{tool_id}.py").write_text(
        _render_pytest_harness(unit_test.pytest_code, tool_id=tool_id),
        encoding="utf-8",
    )
    checks.append(_check_python_compile(tool_root / "tool.py", tool_id=tool_id))
    checks.append(_check_entrypoint_signature(tool_root / "tool.py", tool_id=tool_id))
    checks.append(_check_tool_spec(tool_spec, tool_id=tool_id))
    checks.append(_check_unit_test_harness(unit_test, run_root=run_root, tool_id=tool_id))
    if any(item.status == "failed" for item in checks):
        return checks
    checks.extend(_converge_test_environment(
        test_env_root=test_env_root,
        requirements=[*design.python_requirements, "pytest"],
        tool_id=tool_id,
    ))
    if any(item.status == "failed" for item in checks):
        return checks
    checks.append(_run_pytest(test_env_root=test_env_root, run_root=run_root, tool_id=tool_id))
    if checks[-1].status == "failed":
        return checks
    checks.append(_run_binding_smoke(
        package_root=package_root,
        spec=tool_spec,
        binding_smoke=binding_smoke,
        tool_id=tool_id,
    ))
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


def _check_unit_test_harness(unit_test: ToolUnitTestPlan, *, run_root: Path, tool_id: str) -> ToolManufacturingCheck:
    report_path = run_root / "tool_test_report.json"
    try:
        module = ast.parse(unit_test.pytest_code, filename=f"generated_{tool_id}_tests.py")
        _validate_test_harness_ast(module, tool_id=tool_id)
        return ToolManufacturingCheck(name=f"{tool_id}.unit_test_harness", status="passed")
    except Exception as exc:
        primary_error = f"{type(exc).__name__}: {exc}"
        report_path.write_text(
            json.dumps(
                {
                    "tool_id": tool_id,
                    "phase": "unit_test_harness",
                    "category": "test_harness_violation",
                    "primary_error": primary_error,
                    "pytest_code_preview": unit_test.pytest_code[-4000:],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return _failed_check(
            tool_id=tool_id,
            phase="unit_test_harness",
            category="test_harness_violation",
            primary_error=primary_error,
            report_path=report_path,
            suggested_action="Regenerate pytest logic to call the system-provided run_tool(...) helper or patch tool_module; do not import the generated tool by name.",
        )


def _validate_test_harness_ast(module: ast.Module, *, tool_id: str) -> None:
    forbidden_import_roots = {tool_id, "tools", "importlib", "subprocess"}
    uses_runtime_helper = False
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in forbidden_import_roots:
                    raise ValueError(f"pytest must not import {alias.name}; use run_tool(...) or tool_module from the system harness")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in forbidden_import_roots:
                raise ValueError(f"pytest must not import from {node.module}; use run_tool(...) or tool_module from the system harness")
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "sys" and node.attr == "path":
                raise ValueError("pytest must not mutate sys.path; the system harness owns tool loading")
        elif isinstance(node, ast.Name) and node.id in {"run_tool", "tool_module"}:
            uses_runtime_helper = True
    if not uses_runtime_helper:
        raise ValueError("pytest must exercise the generated tool through run_tool(...) or tool_module")


def _render_pytest_harness(pytest_code: str, *, tool_id: str) -> str:
    module_name = "tool_under_test_" + _safe_path_id(tool_id).replace("-", "_")
    return (
        "from __future__ import annotations\n\n"
        "import importlib.util\n"
        "from pathlib import Path\n"
        "from types import SimpleNamespace\n"
        "from unittest.mock import Mock, patch\n\n"
        "import pytest\n\n"
        f"_TOOL_ID = {tool_id!r}\n"
        "_TOOL_FILE = Path(__file__).resolve().parents[1] / \"package\" / \"tools\" / _TOOL_ID / \"tool.py\"\n"
        f"_SPEC = importlib.util.spec_from_file_location({module_name!r}, _TOOL_FILE)\n"
        "if _SPEC is None or _SPEC.loader is None:\n"
        "    raise RuntimeError(f\"cannot load generated tool from {_TOOL_FILE}\")\n"
        "tool_module = importlib.util.module_from_spec(_SPEC)\n"
        "_SPEC.loader.exec_module(tool_module)\n\n"
        "def run_tool(arguments: dict | None = None, resources: dict | None = None) -> dict:\n"
        "    result = tool_module.run(arguments or {}, resources or {})\n"
        "    assert isinstance(result, dict), \"tool run(...) must return a dict\"\n"
        "    return result\n\n\n"
        "# Model-authored pytest logic starts here. It must use run_tool(...) or tool_module.\n"
        + pytest_code.strip()
        + "\n"
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


def _run_pytest(*, test_env_root: Path, run_root: Path, tool_id: str) -> ToolManufacturingCheck:
    venv_python = _venv_python((Path.cwd() / test_env_root / "venv").resolve())
    started = perf_counter()
    result = subprocess.run(
        [str(venv_python), "-m", "pytest", "-q", str(run_root / "tests")],
        cwd=str(run_root / "package"),
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "PYTHONPATH": str(run_root / "package")},
    )
    report_path = run_root / "tool_test_report.json"
    category = _classify_pytest_failure(result.stdout, result.stderr) if result.returncode != 0 else ""
    primary_error = _extract_primary_error(result.stdout, result.stderr) if result.returncode != 0 else ""
    report_path.write_text(
        json.dumps(
            {
                "tool_id": tool_id,
                "returncode": result.returncode,
                "duration_ms": int((perf_counter() - started) * 1000),
                "category": category,
                "primary_error": primary_error,
                "stdout_preview": result.stdout[-6000:],
                "stderr_preview": result.stderr[-6000:],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if result.returncode != 0:
        primary_error = primary_error or "pytest failed"
        return ToolManufacturingCheck(
            name=f"{tool_id}.unit_tests",
            status="failed",
            message=f"pytest failed: {primary_error}",
            details={
                "report_path": str(report_path),
                "returncode": result.returncode,
                "category": category,
                "primary_error": primary_error,
                "suggested_action": _pytest_suggested_action(category),
            },
            failure_summary=ToolManufacturingFailureSummary(
                tool_id=tool_id,
                phase="unit_tests",
                category=category,
                primary_error=primary_error,
                report_path=str(report_path),
                suggested_action=_pytest_suggested_action(category),
            ),
        )
    return ToolManufacturingCheck(
        name=f"{tool_id}.unit_tests",
        status="passed",
        message="pytest passed",
        details={"report_path": str(report_path)},
    )


def _run_binding_smoke(
    *,
    package_root: Path,
    spec: ToolSpec,
    binding_smoke: ToolBindingSmokePlan,
    tool_id: str,
) -> ToolManufacturingCheck:
    try:
        compiler = ToolCompiler(
            package_root=package_root,
            resources=binding_smoke.resources,
            approval_handler=lambda _spec, _arguments, _risk: ToolApprovalDecision(action="approve"),
        )
        tool = compiler.compile(spec)
        task_model = get_task_model()
        if task_model is None:
            raise ToolManufacturingError("task model is not configured for binding smoke")
        model_result = ModelOperationService(role="task", model=task_model).tool_bound_chat(
            state=None,
            messages=[HumanMessage(content=binding_smoke.user_prompt)],
            tools=[tool],
        )
        ai_message = model_result.ai_message
        if ai_message is None or not getattr(ai_message, "tool_calls", None):
            raise ToolManufacturingError("task model did not emit a tool call")
        _ai, tool_calls = latest_ai_tool_calls([ai_message])
        if not any(str(call.get("name") or "") == binding_smoke.expected_tool_id for call in tool_calls):
            raise ToolManufacturingError("task model emitted an unexpected tool id")
        runner = build_tool_node_runner([tool], node_id="tool_manufacturing_binding_smoke")
        output = runner.invoke({"messages": [ai_message]})
        tool_messages = output.get("messages") or []
        results, failures, _policy, _route = tool_messages_to_runtime_patch(tool_messages)
        if failures:
            raise ToolManufacturingError("; ".join(str(item.get("message") or item) for item in failures))
        if not results:
            raise ToolManufacturingError("ToolNode did not return a completed observation")
        final = ModelOperationService(role="task", model=task_model).tool_bound_chat(
            state=None,
            messages=[
                HumanMessage(content=binding_smoke.user_prompt),
                ai_message if isinstance(ai_message, AIMessage) else AIMessage(content=""),
                *tool_messages,
            ],
            tools=[tool],
        )
        if not (final.final_answer or final.assistant_draft):
            raise ToolManufacturingError("task model did not produce a final answer after tool observation")
        return ToolManufacturingCheck(
            name=f"{tool_id}.binding_smoke",
            status="passed",
            message="tool-bound smoke passed through model, ToolNode, Gateway, ToolMessage, and final answer",
        )
    except Exception as exc:
        return _failed_check(
            tool_id=tool_id,
            phase="binding_smoke",
            category="binding_smoke_error",
            primary_error=f"{type(exc).__name__}: {exc}",
            suggested_action="Regenerate the smoke plan, ToolSpec, or implementation so the tool can pass ToolCompiler, Gateway, ToolNode, and final-answer synthesis.",
        )


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


def _classify_pytest_failure(stdout: str, stderr: str) -> str:
    text = "\n".join([stdout, stderr])
    if "ModuleNotFoundError" in text or "ImportError while importing test module" in text:
        return "test_import_error"
    if "AssertionError" in text or " assert " in text:
        return "assertion_failed"
    if "ValidationError" in text or "schema" in text.lower():
        return "schema_mismatch"
    if "Timeout" in text or "timed out" in text:
        return "test_timeout"
    if "requests." in text or "HTTP" in text:
        return "external_dependency_not_mocked"
    return "pytest_failure"


def _pytest_suggested_action(category: str) -> str:
    if category == "test_import_error":
        return "Regenerate tests to use the system-provided run_tool(...) helper and tool_module instead of importing the generated tool by module name."
    if category == "assertion_failed":
        return "Compare the ToolSpec output schema with implementation behavior; repair either the expected assertion or the implementation."
    if category == "schema_mismatch":
        return "Repair ToolSpec output_schema or implementation output so pytest expectations and runtime schema agree."
    if category == "external_dependency_not_mocked":
        return "Mock network, time, file, and external service calls in pytest; unit tests must not call real services."
    return "Inspect the tool_test_report and regenerate a consistent ToolDesign, implementation, and unit test plan."


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
