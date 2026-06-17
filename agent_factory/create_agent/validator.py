from __future__ import annotations

import ast
import json
from pathlib import Path
import py_compile
import re
import sys
from hashlib import sha256
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML

from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.create_agent.mcp_inheritance import factory_mcp_tool_ids
from agent_factory.create_agent.repair_policy import CreateAgentRepairPolicy
from agent_factory.create_agent.models import (
    PackageToolProbeState,
    PackageValidationIssue,
    PackageValidationReport,
)
from agent_factory.create_agent.runtime_path_repair import find_runtime_path_repairs
from agent_factory.runtime_contracts import AgentPackageLoader, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_contracts.schema import (
    AgentPackageManifest,
    DependenciesContract,
    REQUIRED_AGENT_PACKAGE_CONTRACTS,
    SchedulerSeedContract,
    ToolsContract,
)
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.persistence import LangGraphCheckpointerConfig, LangGraphStoreConfig
from agent_factory.runtime_kernel.planning import PLAN_AND_EXECUTE_PATTERN_ID, RUNTIME_PLAN_TOOL_ID
from agent_factory.tooling.builtins.registry import get_builtin_tool_ids
from agent_factory.tooling.providers import PackageToolProvider, ToolProviderContext
from agent_factory.tooling.skills.schema import SkillGatewayState


ValidationScope = str
REPAIR_POLICY = CreateAgentRepairPolicy()
CREATE_AGENT_RUNTIME_PATTERN_ID = "react_agent"
CREATE_AGENT_RUNTIME_PATTERN_IDS = {CREATE_AGENT_RUNTIME_PATTERN_ID, PLAN_AND_EXECUTE_PATTERN_ID}


class CreateAgentPackageValidator:
    def validate(
        self,
        package_root: str | Path,
        *,
        scope: ValidationScope = "full_static",
        changed_files: list[str] | None = None,
    ) -> PackageValidationReport:
        root = Path(package_root).expanduser().resolve()
        changed = list(changed_files or [])
        hygiene = _workspace_hygiene(root, changed)
        if hygiene is not None:
            return _with_scope(hygiene, scope=scope, changed_files=changed)
        if scope == "workspace_hygiene":
            return _passed(root, scope=scope, changed_files=changed, summary="Workspace hygiene checks passed.")
        manifest_path = root / "agent_package.json"
        if not manifest_path.exists():
            repair_bundle = REPAIR_POLICY.manifest_missing_bundle()
            return _with_scope(
                PackageValidationReport(
                    package_root=str(root),
                    summary="agent_package.json is missing.",
                    issues=[
                        PackageValidationIssue(
                            where="package.manifest",
                            summary="agent_package.json is missing",
                            message="The workspace does not contain agent_package.json.",
                            path="agent_package.json",
                            expected="agent_package.json exists at the package root",
                            actual="missing",
                            repair_hint="Create agent_package.json with package-relative contract and assembly references.",
                            target_files=["agent_package.json"],
                            recommended_skill=repair_bundle.recommended_skill,
                            recommended_resources=repair_bundle.recommended_resources,
                            repair_bundle=repair_bundle,
                        )
                    ],
                ),
                scope=scope,
                changed_files=changed,
            )
        manifest_shape_report = _manifest_shape_report(root, manifest_path, scope=scope, changed_files=changed)
        if manifest_shape_report is not None:
            return manifest_shape_report

        # JSON syntax validation: check all JSON files before attempting to load
        json_syntax_report = _json_syntax_report(root, scope=scope, changed_files=changed)
        if json_syntax_report is not None:
            return json_syntax_report
        if scope == "package_shape":
            try:
                AgentPackageManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                return _failed(root, "package.manifest", exc, ["agent_package.json"], scope=scope, changed_files=changed)
            return _passed(root, scope=scope, changed_files=changed, summary="Package shape checks passed.")

        try:
            package = AgentPackageLoader().load_path(manifest_path)
        except Exception as exc:
            load_report = _package_load_schema_report(root, exc, scope=scope, changed_files=changed)
            if load_report is not None:
                return load_report
            return _failed(root, "package.load", exc, ["agent_package.json"], scope=scope, changed_files=changed)
        runtime_path_report = _runtime_path_report(root, package, scope=scope, changed_files=changed)
        if runtime_path_report is not None:
            return runtime_path_report
        file_contract_report = _package_file_contract_report(root, package, scope=scope, changed_files=changed)
        if file_contract_report is not None:
            return file_contract_report
        if scope in {"python_syntax", "full_static"}:
            syntax_report = _python_syntax(root, changed)
            if syntax_report is not None:
                return _with_scope(syntax_report, scope=scope, changed_files=changed)
        try:
            compiler = _static_validation_compiler()
            runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=compiler.facade.instance.services,
            )
        except Exception as exc:
            runtime_contract_report = _runtime_contract_build_report(root, package, exc, scope=scope, changed_files=changed)
            if runtime_contract_report is not None:
                return runtime_contract_report
            return _failed(root, "runtime_contracts.build", exc, ["agent_package.json", "contracts"], scope=scope, changed_files=changed)
        if scope == "runtime_contract_build":
            return _passed(root, scope=scope, changed_files=changed, summary="Runtime contract build checks passed.")
        try:
            binding_target_report = _binding_target_report(
                root,
                package,
                compiler.facade.instance.pattern_registry,
                scope=scope,
                changed_files=changed,
            )
            if binding_target_report is not None:
                return binding_target_report
            compiler.compile(package.assembly_spec, runtime_build=runtime_build)
        except Exception as exc:
            return _failed(root, "assembly.compile", exc, ["assembly_spec.json"], scope=scope, changed_files=changed)
        if scope != "full_static":
            return _passed(root, scope=scope, changed_files=changed, summary="Assembly compile checks passed.")
        # Full static: semantic completeness gate
        semantic_report = _semantic_completeness_report(root, package, scope=scope, changed_files=changed)
        if semantic_report is not None:
            return semantic_report
        probe_report = _package_tool_probe_report(root, package, scope=scope, changed_files=changed)
        if probe_report is not None:
            return probe_report
        return _passed(root, scope=scope, changed_files=changed, summary="Package static validation passed.")


def _static_validation_compiler() -> AgentAssemblyCompiler:
    return AgentAssemblyCompiler(
        facade=RuntimeKernelFacade(
            checkpointer_config=LangGraphCheckpointerConfig(backend="memory"),
            memory_store_config=LangGraphStoreConfig(backend="memory"),
        )
    )


def _passed(root: Path, *, scope: ValidationScope, changed_files: list[str], summary: str) -> PackageValidationReport:
    return PackageValidationReport(
        status="passed",
        package_root=str(root),
        validation_scope=scope,  # type: ignore[arg-type]
        changed_files=changed_files,
        summary=summary,
    )


def _failed(
    root: Path,
    where: str,
    exc: Exception,
    target_files: list[str],
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport:
    repair_bundle = REPAIR_POLICY.generic_bundle(where=where, target_files=target_files, exc=exc)
    return PackageValidationReport(
        package_root=str(root),
        validation_scope=scope,  # type: ignore[arg-type]
        changed_files=changed_files,
        summary=f"{where} failed: {type(exc).__name__}: {exc}",
        issues=[
            PackageValidationIssue(
                where=where,
                summary=f"{type(exc).__name__}: {exc}",
                message=str(exc),
                path=target_files[0] if target_files else "",
                expected=REPAIR_POLICY.expected_for_where(where),
                actual=f"{type(exc).__name__}: {exc}",
                repair_hint=REPAIR_POLICY.repair_hint(where),
                target_files=target_files,
                recommended_skill=repair_bundle.recommended_skill,
                recommended_resources=repair_bundle.recommended_resources,
                repair_bundle=repair_bundle,
                details=_exception_details(exc),
            )
        ],
    )


def _package_load_schema_report(
    root: Path,
    exc: Exception,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    if not isinstance(exc, ValidationError):
        return None
    issues: list[PackageValidationIssue] = []
    for error in exc.errors():
        issue = _schema_repair_issue_from_pydantic_error(error)
        if issue is not None:
            issues.append(issue)
    if not issues:
        return None
    target_files = sorted({target for issue in issues for target in issue.target_files})
    repair_bundle = REPAIR_POLICY.generic_bundle(
        where="package.load.schema",
        target_files=target_files or ["agent_package.json"],
        exc=exc,
    )
    for index, issue in enumerate(issues):
        if issue.repair_bundle is None:
            issues[index] = issue.model_copy(update={"repair_bundle": repair_bundle})
    return PackageValidationReport(
        package_root=str(root),
        validation_scope=scope,  # type: ignore[arg-type]
        changed_files=changed_files,
        summary="package.load.schema failed: package files do not match executable runtime schemas.",
        issues=issues,
    )


def _schema_repair_issue_from_pydantic_error(error: dict[str, Any]) -> PackageValidationIssue | None:
    loc = tuple(str(item) for item in error.get("loc", ()))
    error_type = str(error.get("type") or "")
    message = str(error.get("msg") or "")
    input_value = error.get("input")
    if _loc_contains(loc, "tools"):
        index = _loc_index_after(loc, "tools")
        invalid_path = "assembly_spec.json:/tools" + (f"/{index}" if index is not None else "")
        return PackageValidationIssue(
            where="package.load.schema.assembly_tools",
            summary="assembly_spec.json tools entries must be ToolSpec objects",
            message=message,
            path="assembly_spec.json",
            expected="AgentAssemblySpec.tools is an array of ToolSpec objects.",
            actual=_compact_actual(input_value),
            repair_hint="Replace the invalid tools item with a complete ToolSpec object and ensure the package tool manifest uses the same shape.",
            target_files=["assembly_spec.json", "tools/"],
            recommended_skill="12-assembly-pattern-system",
            recommended_resources=[
                "examples/assembly_spec.with_tools_and_bindings.json",
            ],
            schema_path="AgentAssemblySpec.tools[]",
            invalid_value_path=invalid_path,
            expected_shape=_tool_spec_expected_shape(),
            repair_template=_tool_spec_repair_template(),
            replace_strategy="replace_array_item",
            details={"pydantic_error": error, "error_type": error_type},
        )
    if _loc_contains(loc, "node_bindings"):
        index = _loc_index_after(loc, "node_bindings")
        invalid_path = "assembly_spec.json:/bindings/node_bindings" + (f"/{index}" if index is not None else "")
        return PackageValidationIssue(
            where="package.load.schema.node_binding",
            summary="assembly_spec.json node_bindings entries must be NodeBinding objects",
            message=message,
            path="assembly_spec.json",
            expected="BindingSet.node_bindings is an array of NodeBinding objects with binding_id, binding_type, target, and payload.",
            actual=_compact_actual(input_value),
            repair_hint="Move node_id/provider_id style fields into target or payload, and replace the invalid binding with a complete NodeBinding object.",
            target_files=["assembly_spec.json"],
            recommended_skill="12-assembly-pattern-system",
            recommended_resources=[
                "examples/assembly_spec.with_tools_and_bindings.json",
                "references/final_validation.repair_mappings.json",
            ],
            schema_path="AgentAssemblySpec.bindings.node_bindings[]",
            invalid_value_path=invalid_path,
            expected_shape=_node_binding_expected_shape(),
            repair_template=_node_binding_repair_template(),
            replace_strategy="replace_array_item",
            details={"pydantic_error": error, "error_type": error_type},
        )
    if _loc_contains(loc, "contracts"):
        return PackageValidationIssue(
            where="package.load.schema.manifest_contracts",
            summary="agent_package.json contracts must use package-relative file references",
            message=message,
            path="agent_package.json",
            expected="agent_package.json contracts is an object mapping required contract keys to package-relative paths.",
            actual=_compact_actual(input_value),
            repair_hint="Rewrite the manifest contract reference and create the referenced file when it is missing.",
            target_files=["agent_package.json"],
            recommended_skill="01-package-identity-system",
            recommended_resources=["references/package_identity.schema.json"],
            schema_path="AgentPackageManifest.contracts",
            invalid_value_path="agent_package.json:/contracts",
            expected_shape={"contracts": {"tools": "contracts/tools.json"}},
            repair_template={"contracts": {"<required_contract_key>": "contracts/<required_contract_key>.json"}},
            replace_strategy="replace_object",
            details={"pydantic_error": error, "error_type": error_type},
        )
    return None


def _loc_contains(loc: tuple[str, ...], segment: str) -> bool:
    return segment in loc


def _loc_index_after(loc: tuple[str, ...], segment: str) -> str | None:
    try:
        value = loc[loc.index(segment) + 1]
    except (ValueError, IndexError):
        return None
    return value if value.isdigit() else None


def _compact_actual(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)[:500]
    except TypeError:
        return str(value)[:500]


def _tool_spec_expected_shape() -> dict[str, Any]:
    return {
        "id": "snake_case_tool_id",
        "description": "What the tool does.",
        "entrypoint": "python:tools/snake_case_tool_id/tool.py:run",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": {"type": "object", "properties": {}, "additionalProperties": True},
        "resources": {},
        "risk_level": "low|medium|high",
        "risk_evaluator": {"llm_mode": "disabled"},
        "concurrent": True,
    }


def _tool_spec_repair_template() -> dict[str, Any]:
    return {
        "id": "<tool_id>",
        "description": "<specific runtime capability>",
        "entrypoint": "python:tools/<tool_id>/tool.py:run",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "result": {"type": "string"},
            },
            "required": ["result"],
            "additionalProperties": True,
        },
        "resources": {},
        "risk_level": "low",
        "risk_evaluator": {"llm_mode": "disabled"},
        "concurrent": True,
    }


def _node_binding_expected_shape() -> dict[str, Any]:
    return {
        "binding_id": "snake_case_binding_id",
        "binding_type": "prompt|tool_access|model_operation|strategy_profile|output_formatter|custom",
        "target": {"node_id": "pattern_node_id", "impl": "node.impl"},
        "payload": {},
    }


def _node_binding_repair_template() -> dict[str, Any]:
    return {
        "binding_id": "<node_id>_tools",
        "binding_type": "tool_access",
        "target": {"node_id": "<node_id>", "impl": "cognitive.answer"},
        "payload": {
            "allowed_tool_ids": ["<tool_id>"],
            "approval_policy": "standard",
        },
    }


def _manifest_shape_report(
    root: Path,
    manifest_path: Path,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    contracts = payload.get("contracts")
    if not isinstance(contracts, dict):
        return None
    missing_contracts = sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS - {str(key) for key in contracts})
    missing_files = [
        (str(key), str(value))
        for key, value in sorted(contracts.items())
        if isinstance(value, str) and value.strip() and not (root / value).is_file()
    ]
    if not missing_contracts and not missing_files:
        return None
    targets = REPAIR_POLICY.manifest_contract_targets(
        missing_contracts=missing_contracts,
        missing_files=missing_files,
    )
    target_files = sorted({"agent_package.json", *(target.target_file for target in targets)})
    summary_parts = []
    if missing_contracts:
        summary_parts.append("missing required contracts: " + ", ".join(missing_contracts))
    if missing_files:
        summary_parts.append("missing referenced package files: " + ", ".join(path for _key, path in missing_files))
    summary = "; ".join(summary_parts)
    repair_bundle = REPAIR_POLICY.manifest_contract_bundle(
        missing_contracts=missing_contracts,
        missing_files=missing_files,
        target_files=target_files,
        targets=targets,
        summary=summary,
    )
    issue = PackageValidationIssue(
        where="package.manifest_contracts",
        summary=summary,
        message=summary,
        path="agent_package.json",
        expected="agent_package.json declares all RuntimeKernel required contracts and every referenced file exists.",
        actual=summary,
        repair_hint="Repair agent_package.json and the referenced package files using validator targets and recommended skill resources, then rerun validation.",
        target_files=target_files,
        recommended_skill=repair_bundle.recommended_skill,
        recommended_resources=repair_bundle.recommended_resources,
        repair_bundle=repair_bundle,
        details={"missing_contracts": missing_contracts, "missing_files": repair_bundle.inputs["missing_files"]},
    )
    return _with_scope(
        PackageValidationReport(
            package_root=str(root),
            summary=f"package.manifest_contracts failed: {summary}",
            issues=[issue],
        ),
        scope=scope,
        changed_files=changed_files,
    )

def _runtime_path_report(
    root: Path,
    package: Any,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    repairs = find_runtime_path_repairs(
        package_root=root,
        contract_paths=package.manifest.contracts,
        contracts=package.contracts,
    )
    if not repairs:
        return None
    bundles = [REPAIR_POLICY.runtime_path_bundle(repair.to_input()) for repair in repairs]
    issues = []
    for repair, bundle in zip(repairs, bundles, strict=True):
        issues.append(
            PackageValidationIssue(
                where="runtime_contracts.path",
                summary=f"{repair.contract_key}.{repair.field_path} escapes package workspace",
                message=(
                    f"{repair.contract_key}.{repair.field_path} is {repair.current_value!r}; "
                    f"use package-relative {repair.replacement_value!r}."
                ),
                path=repair.target_file,
                expected="Runtime contract filesystem paths resolve inside the package workspace.",
                actual=repair.current_value,
                repair_hint="Apply the machine repair bundle to normalize runtime contract paths.",
                target_files=[repair.target_file],
                recommended_skill=bundle.recommended_skill,
                recommended_resources=bundle.recommended_resources,
                repair_bundle=bundle,
                details=repair.to_input(),
            )
        )
    target_files = sorted({repair.target_file for repair in repairs})
    return _with_scope(
        PackageValidationReport(
            package_root=str(root),
            summary="runtime_contracts.path failed: runtime contract paths must be package-relative.",
            issues=issues,
        ),
        scope=scope,
        changed_files=changed_files,
    )


def _runtime_contract_build_report(
    root: Path,
    package: Any,
    exc: Exception,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    if not isinstance(exc, ValidationError):
        return None
    issues: list[PackageValidationIssue] = []
    for error in exc.errors():
        issue = _runtime_contract_issue_from_pydantic_error(package, error)
        if issue is not None:
            issues.append(issue)
    if not issues:
        return None
    return _issues_report(
        root,
        issues,
        scope=scope,
        changed_files=changed_files,
        summary="Runtime contract build check failed: " + "; ".join(issue.summary for issue in issues[:3]),
    )


def _runtime_contract_issue_from_pydantic_error(package: Any, error: dict[str, Any]) -> PackageValidationIssue | None:
    loc = tuple(str(item) for item in error.get("loc", ()))
    message = str(error.get("msg") or "")
    input_value = error.get("input")
    if _scheduler_seed_error(loc=loc, message=message, input_value=input_value):
        invalid_path = _scheduler_seed_invalid_path(loc)
        summary = _scheduler_seed_summary(loc=loc, message=message)
        return PackageValidationIssue(
            where="scheduler_seed.target_payload",
            summary=summary,
            message=message,
            path=_contract_path(package, "scheduler_seed"),
            expected="SchedulerSeedContract graph_run targets use payload.message to describe the scheduled agent run.",
            actual=_compact_actual(input_value),
            repair_hint="Rewrite the scheduler seed target payload with a message field, then call create_agent_validate with the appropriate scope.",
            target_files=[_contract_path(package, "scheduler_seed")],
            recommended_skill="15-scheduler-seed-system",
            recommended_resources=[
                "examples/scheduler_seed_system.capability.json",
                "references/scheduler_seed_system.repair_hints.md",
            ],
            schema_path="SchedulerSeedContract.config.seeds[].target.payload.message",
            invalid_value_path=invalid_path,
            expected_shape={
                "target": {
                    "target_type": "graph_run",
                    "payload": {
                        "message": "Natural-language instruction for the scheduled agent run.",
                        "thread_policy": "new_thread_per_run",
                    },
                }
            },
            repair_template={
                "target": {
                    "target_type": "graph_run",
                    "payload": {
                        "message": "<scheduled task instruction from task_content/user request>",
                        "thread_policy": "new_thread_per_run",
                    },
                }
            },
            replace_strategy="replace_object",
            details={"pydantic_error": error},
        )
    if _loc_contains(loc, "seeds"):
        return PackageValidationIssue(
            where="scheduler_seed.schema",
            summary="contracts/scheduler_seed.json does not match SchedulerSeedContract",
            message=message,
            path=_contract_path(package, "scheduler_seed"),
            expected="contracts/scheduler_seed.json follows scheduler_seed_contract.v0.",
            actual=_compact_actual(input_value),
            repair_hint="Repair only contracts/scheduler_seed.json using scheduler seed validator evidence.",
            target_files=[_contract_path(package, "scheduler_seed")],
            recommended_skill="15-scheduler-seed-system",
            recommended_resources=[
                "examples/scheduler_seed_system.capability.json",
                "references/scheduler_seed_system.repair_hints.md",
            ],
            schema_path="SchedulerSeedContract.config.seeds[]",
            invalid_value_path=_scheduler_seed_invalid_path(loc),
            details={"pydantic_error": error},
        )
    return None


def _scheduler_seed_error(*, loc: tuple[str, ...], message: str, input_value: Any) -> bool:
    if not _loc_contains(loc, "target"):
        return False
    if "graph_run target payload requires message" in message:
        return True
    if isinstance(input_value, dict):
        payload = input_value.get("payload")
        return input_value.get("target_type") == "graph_run" and isinstance(payload, dict) and "message" not in payload
    return False


def _scheduler_seed_summary(*, loc: tuple[str, ...], message: str) -> str:
    index = _loc_index_after(loc, "seeds")
    seed_label = f"seed {index}" if index is not None else "scheduler seed"
    if "payload requires message" in message:
        return f"{seed_label} graph_run target payload is missing message"
    return f"{seed_label} target payload is invalid"


def _scheduler_seed_invalid_path(loc: tuple[str, ...]) -> str:
    path = "contracts/scheduler_seed.json"
    if loc:
        path += ":/" + "/".join(loc)
    return path


def _contract_path(package: Any, contract_key: str) -> str:
    manifest = getattr(package, "manifest", None)
    contracts = getattr(manifest, "contracts", {}) if manifest is not None else {}
    if isinstance(contracts, dict):
        value = contracts.get(contract_key)
        if isinstance(value, str) and value.strip():
            return value
    return f"contracts/{contract_key}.json"


def _with_scope(report: PackageValidationReport, *, scope: ValidationScope, changed_files: list[str]) -> PackageValidationReport:
    return report.model_copy(update={"validation_scope": scope, "changed_files": changed_files})


def _workspace_hygiene(root: Path, changed_files: list[str]) -> PackageValidationReport | None:
    yaml = YAML(typ="safe")
    for relative in changed_files:
        path = root / relative
        if not path.exists() or not path.is_file():
            continue
        try:
            if path.suffix == ".json":
                json.loads(path.read_text(encoding="utf-8"))
            elif path.suffix in {".yaml", ".yml"}:
                yaml.load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            repair_bundle = REPAIR_POLICY.generic_bundle(
                where="workspace_hygiene.parse",
                target_files=[relative],
                exc=exc,
            )
            return PackageValidationReport(
                package_root=str(root),
                summary=f"{relative} is not parseable: {type(exc).__name__}: {exc}",
                issues=[
                    PackageValidationIssue(
                        where="workspace_hygiene.parse",
                        summary=f"{relative} is not parseable",
                        message=str(exc),
                        path=relative,
                        expected="valid JSON or YAML syntax",
                        actual=f"{type(exc).__name__}: {exc}",
                        repair_hint="Repair the file syntax before continuing package validation.",
                        target_files=[relative],
                        recommended_skill=repair_bundle.recommended_skill,
                        recommended_resources=repair_bundle.recommended_resources,
                        repair_bundle=repair_bundle,
                        details=_exception_details(exc),
                    )
                ],
            )
    return None


def _json_syntax_report(
    root: Path,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    """Validate JSON syntax of all critical package files.

    This catches common LLM-generated JSON errors (trailing commas, extra braces)
    before they cause runtime loading failures.
    """
    critical_json_files = [
        ("agent_package.json", None),
        ("assembly_spec.json", None),
        ("render_manifest.json", None),
        (".factory/skill_gateway_state.json", SkillGatewayState),
        (".factory/todo.json", None),
        (".factory/action.json", None),
    ]

    # Add contract files
    manifest_path = root / "agent_package.json"
    if manifest_path.exists():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(manifest_data.get("contracts"), dict):
                for contract_key, contract_path in manifest_data["contracts"].items():
                    critical_json_files.append((contract_path, None))
        except (json.JSONDecodeError, FileNotFoundError):
            pass  # Will be caught by per-file check below

    for relative_path, model_class in critical_json_files:
        file_path = root / relative_path
        if not file_path.exists():
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
            # First check: raw JSON syntax
            parsed = json.loads(content)

            # Second check: if model class provided, validate schema
            if model_class is not None:
                model_class.model_validate(parsed)

        except json.JSONDecodeError as exc:
            # Extract helpful error context
            error_msg = str(exc)
            repair_hint = _json_error_repair_hint(error_msg)

            repair_bundle = REPAIR_POLICY.generic_bundle(
                where="json_syntax",
                target_files=[relative_path],
                exc=exc,
            )

            return _with_scope(
                PackageValidationReport(
                    package_root=str(root),
                    summary=f"JSON syntax error in {relative_path}: {error_msg}",
                    issues=[
                        PackageValidationIssue(
                            where="json_syntax",
                            summary=f"Invalid JSON syntax in {relative_path}",
                            message=error_msg,
                            path=relative_path,
                            expected="Valid JSON syntax without trailing commas, extra braces, or unterminated strings",
                            actual=f"JSONDecodeError: {error_msg}",
                            repair_hint=repair_hint,
                            target_files=[relative_path],
                            recommended_skill=repair_bundle.recommended_skill,
                            recommended_resources=repair_bundle.recommended_resources,
                            repair_bundle=repair_bundle,
                            details={"line": getattr(exc, "lineno", None), "column": getattr(exc, "colno", None)},
                        )
                    ],
                ),
                scope=scope,
                changed_files=changed_files,
            )
        except ValidationError as exc:
            # Pydantic schema validation failed
            repair_bundle = REPAIR_POLICY.generic_bundle(
                where="json_schema",
                target_files=[relative_path],
                exc=exc,
            )

            return _with_scope(
                PackageValidationReport(
                    package_root=str(root),
                    summary=f"JSON schema validation error in {relative_path}",
                    issues=[
                        PackageValidationIssue(
                            where="json_schema",
                            summary=f"Invalid JSON schema in {relative_path}",
                            message=str(exc),
                            path=relative_path,
                            expected=f"Valid {model_class.__name__} schema",
                            actual=f"ValidationError: {exc}",
                            repair_hint=f"Fix the JSON structure to match {model_class.__name__} schema. Common issues: missing required fields, wrong field types, extra fields not allowed.",
                            target_files=[relative_path],
                            recommended_skill=repair_bundle.recommended_skill,
                            recommended_resources=repair_bundle.recommended_resources,
                            repair_bundle=repair_bundle,
                            details=_exception_details(exc),
                        )
                    ],
                ),
                scope=scope,
                changed_files=changed_files,
            )

    return None


def _json_error_repair_hint(error_msg: str) -> str:
    """Generate specific repair hints based on JSON error message."""
    error_lower = error_msg.lower()

    if "trailing comma" in error_lower or "expecting property name" in error_lower:
        return "Remove trailing commas before closing braces/brackets. Example: {\"a\": 1,} → {\"a\": 1}"

    if "trailing characters" in error_lower or "extra data" in error_lower:
        return "Remove extra characters after the closing brace. Check for duplicate closing braces or commas outside the JSON structure."

    if "unterminated string" in error_lower:
        return "Add missing closing quote for string values. Check for unescaped quotes inside strings."

    if "expecting" in error_lower:
        return "Check for missing commas between object properties or array elements, or missing closing braces/brackets."

    return "Fix JSON syntax. Common issues: trailing commas, extra/missing braces, unescaped quotes, missing commas."


def _python_syntax(root: Path, changed_files: list[str]) -> PackageValidationReport | None:
    candidates = [root / item for item in changed_files if item.endswith(".py")]
    if not candidates and (root / "tools").exists():
        candidates.extend(sorted((root / "tools").glob("**/*.py")))
    if not candidates and (root / "nodes").exists():
        candidates.extend(sorted((root / "nodes").glob("**/*.py")))
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            relative = _relative(root, path)
            repair_bundle = REPAIR_POLICY.generic_bundle(
                where="python_syntax.compile",
                target_files=[relative],
                exc=exc,
            )
            return PackageValidationReport(
                package_root=str(root),
                summary=f"{relative} failed Python syntax validation: {type(exc).__name__}: {exc}",
                issues=[
                    PackageValidationIssue(
                        where="python_syntax.compile",
                        summary=f"{relative} failed Python syntax validation",
                        message=str(exc),
                        path=relative,
                        expected="valid Python syntax",
                        actual=f"{type(exc).__name__}: {exc}",
                        repair_hint="Fix the generated Python entrypoint syntax and keep dependencies declared in the package.",
                        target_files=[relative],
                        recommended_skill=repair_bundle.recommended_skill,
                        recommended_resources=repair_bundle.recommended_resources,
                        repair_bundle=repair_bundle,
                        details=_exception_details(exc),
                    )
                ],
            )
    return None


def _package_file_contract_report(
    root: Path,
    package: Any,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    issues: list[PackageValidationIssue] = []
    manifest = package.manifest
    package_result = PackageToolProvider().discover(ToolProviderContext(package_root=root))
    package_tools = {spec.id: spec for spec in package_result.tool_specs}
    for diagnostic in package_result.diagnostics:
        if diagnostic.level == "error":
            manifest_path = str(diagnostic.details.get("manifest_path") or "tools/")
            issues.append(_contract_issue(
                where="package_tool.manifest_load",
                summary=diagnostic.message,
                message=str(diagnostic.details.get("error") or diagnostic.message),
                path=_relative(root, Path(manifest_path)),
                expected="Every tools/<id>/manifest.json loads as a ToolSpec.",
                actual=str(diagnostic.details.get("error") or diagnostic.message),
                repair_hint="Repair the package tool manifest so PackageToolProvider can load it.",
                target_files=[_relative(root, Path(manifest_path))],
                recommended_skill="10-package-tool-system",
            ))
    issues.extend(_runtime_pattern_alignment_issues(package))
    issues.extend(_manifest_asset_index_issues(root, manifest, package_tools))
    issues.extend(_tools_contract_issues(package))
    issues.extend(_tool_dependency_issues(root, package, package_tools))
    issues.extend(_assembly_tool_issues(package, package_tools))
    inherited_mcp_tools = _inherited_mcp_tool_ids()
    issues.extend(_tool_access_issues(package, package_tools, inherited_mcp_tools))
    issues.extend(_scheduler_tool_target_issues(package, package_tools, inherited_mcp_tools))
    if not issues:
        return None
    return _issues_report(
        root,
        issues,
        scope=scope,
        changed_files=changed_files,
        summary="Package file contract check failed: " + "; ".join(issue.summary for issue in issues[:3]),
    )


def _runtime_pattern_alignment_issues(package: Any) -> list[PackageValidationIssue]:
    manifest_pattern = str((getattr(package.manifest, "runtime", {}) or {}).get("pattern_id") or "")
    assembly_pattern = str(getattr(getattr(package.assembly_spec, "runtime", None), "pattern_id", "") or "")
    if manifest_pattern == assembly_pattern:
        return []
    return [
        _contract_issue(
            where="package.runtime_pattern_alignment",
            summary="agent_package.json runtime pattern does not match assembly_spec.json runtime pattern",
            message="The package manifest and assembly spec must point to the same built-in runtime pattern.",
            path="agent_package.json",
            expected="agent_package.json.runtime.pattern_id equals assembly_spec.json.runtime.pattern_id.",
            actual=f"agent_package.json={manifest_pattern or '<empty>'}; assembly_spec.json={assembly_pattern or '<empty>'}",
            repair_hint="Update agent_package.json.runtime.pattern_id or assembly_spec.json.runtime.pattern_id so they match.",
            target_files=["agent_package.json", "assembly_spec.json", "render_manifest.json"],
            recommended_skill="01-package-identity-system",
        )
    ]


def _binding_target_report(
    root: Path,
    package: Any,
    pattern_registry: Any,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    issues = _binding_target_issues(package, pattern_registry)
    if not issues:
        return None
    return _issues_report(
        root,
        issues,
        scope=scope,
        changed_files=changed_files,
        summary="Assembly binding target check failed: " + "; ".join(issue.summary for issue in issues[:3]),
    )


def _binding_target_issues(package: Any, pattern_registry: Any) -> list[PackageValidationIssue]:
    pattern_id = str(getattr(getattr(package.assembly_spec, "runtime", None), "pattern_id", "") or "")
    if pattern_id not in CREATE_AGENT_RUNTIME_PATTERN_IDS:
        return [
            _contract_issue(
                where="assembly.binding_target.pattern",
                summary="create-agent currently supports only built-in react_agent and plan_and_execute runtime patterns",
                message=(
                    "Use a supported built-in runtime pattern and express capability through prompt bindings, tool access, package tools, knowledge, memory, scheduler, and resources."
                ),
                path="assembly_spec.json",
                expected='assembly_spec.runtime.pattern_id is "react_agent" or "plan_and_execute".',
                actual=pattern_id or "<empty>",
                repair_hint='Set assembly_spec.runtime.pattern_id to "react_agent" for direct ReAct or "plan_and_execute" for planned execution.',
                target_files=["assembly_spec.json", "agent_package.json"],
                recommended_skill="12-assembly-pattern-system",
            )
        ]
    try:
        pattern = pattern_registry.get(pattern_id)
    except Exception as exc:
        return [
            _contract_issue(
                where="assembly.binding_target.pattern",
                summary=f"assembly runtime pattern {pattern_id or '<empty>'} is not available",
                message=f"Cannot validate binding targets because the runtime pattern cannot be loaded: {type(exc).__name__}: {exc}",
                path="assembly_spec.json",
                expected="assembly_spec.runtime.pattern_id references a supported built-in runtime pattern.",
                actual=pattern_id or "<empty>",
                repair_hint='Set assembly_spec.runtime.pattern_id to "react_agent" or "plan_and_execute".',
                target_files=["assembly_spec.json"],
                recommended_skill="12-assembly-pattern-system",
            )
        ]
    node_impls = {node.id: node.impl for node in pattern.nodes}
    issues: list[PackageValidationIssue] = []
    prompt_bindings: dict[tuple[str, str, str], Any] = {}
    for index, binding in enumerate(package.assembly_spec.bindings.node_bindings):
        target = getattr(binding, "target", None)
        node_id = str(getattr(target, "node_id", "") or "")
        impl = str(getattr(target, "impl", "") or "")
        actual_impl = node_impls.get(node_id)
        if actual_impl is None:
            issues.append(_binding_target_issue(
                index=index,
                binding=binding,
                expected=f"target.node_id is one of: {', '.join(sorted(node_impls))}",
                actual=f"{node_id or '<empty>'}.{impl or '<empty>'}",
                summary=f"binding {binding.binding_id} targets unknown pattern node {node_id or '<empty>'}",
                message=f"The selected pattern {pattern.pattern_id} has no node id {node_id or '<empty>'}.",
                repair_template={"target": {"node_id": "<pattern_node_id>", "impl": "<pattern_node_impl>"}},
            ))
            continue
        if impl != actual_impl:
            issues.append(_binding_target_issue(
                index=index,
                binding=binding,
                expected=f"target.impl for node {node_id} is {actual_impl}",
                actual=impl or "<empty>",
                summary=f"binding {binding.binding_id} target impl does not match pattern node {node_id}",
                message=f"The selected pattern {pattern.pattern_id} defines node {node_id} with impl {actual_impl}, but the binding targets {impl or '<empty>'}.",
                repair_template={"target": {"node_id": node_id, "impl": actual_impl}},
            ))
            continue
        if binding.binding_type == "prompt":
            payload = getattr(binding, "payload", None)
            prompt_id = str(getattr(payload, "prompt_id", "") or "")
            if prompt_id:
                prompt_bindings[(node_id, impl, prompt_id)] = binding
    for index, binding in enumerate(package.assembly_spec.bindings.node_bindings):
        if binding.binding_type != "model_operation":
            continue
        target = getattr(binding, "target", None)
        node_id = str(getattr(target, "node_id", "") or "")
        impl = str(getattr(target, "impl", "") or "")
        actual_impl = node_impls.get(node_id)
        if actual_impl != impl:
            continue
        payload = getattr(binding, "payload", None)
        prompt_id = str(getattr(payload, "prompt_id", "") or "").strip()
        if not prompt_id:
            continue
        if (node_id, impl, prompt_id) in prompt_bindings:
            continue
        issues.append(_binding_target_issue(
            index=index,
            binding=binding,
            expected=f"a prompt binding with target {node_id}.{impl} and payload.prompt_id={prompt_id}",
            actual="missing prompt binding for model_operation.prompt_id",
            summary=f"model_operation binding {binding.binding_id} references missing prompt_id {prompt_id}",
            message="Prompt bindings are node-scoped; model_operation.prompt_id must resolve to a prompt binding on the same pattern node and impl.",
            repair_template={
                "binding_id": f"{node_id}_prompt",
                "binding_type": "prompt",
                "target": {"node_id": node_id, "impl": impl},
                "payload": {"prompt_id": prompt_id, "template": "<system prompt>", "variables": []},
            },
        ))
    if pattern_id == PLAN_AND_EXECUTE_PATTERN_ID:
        issues.extend(_plan_and_execute_binding_issues(package))
    return issues


def _plan_and_execute_binding_issues(package: Any) -> list[PackageValidationIssue]:
    bindings = list(package.assembly_spec.bindings.node_bindings)
    issues: list[PackageValidationIssue] = []
    for node_id in ("planner", "executor", "final_answer"):
        if not _has_binding(bindings, node_id=node_id, binding_type="prompt"):
            issues.append(_missing_plan_binding_issue(node_id=node_id, binding_type="prompt"))
        if not _has_binding(bindings, node_id=node_id, binding_type="model_operation"):
            issues.append(_missing_plan_binding_issue(node_id=node_id, binding_type="model_operation"))
    planner_tools = _tool_access_for_node(bindings, node_id="planner")
    if planner_tools != [RUNTIME_PLAN_TOOL_ID]:
        issues.append(_contract_issue(
            where="assembly.plan_and_execute.planner_tools",
            summary="plan_and_execute planner must only expose runtime_plan",
            message="The planner creates dynamic plan state and must not call business tools.",
            path="assembly_spec.json",
            expected='planner tool_access.allowed_tool_ids is ["runtime_plan"].',
            actual=", ".join(planner_tools) if planner_tools else "<missing>",
            repair_hint='Add planner tool_access with only "runtime_plan".',
            target_files=["assembly_spec.json"],
            recommended_skill="12-assembly-pattern-system",
        ))
    executor_tools = _tool_access_for_node(bindings, node_id="executor")
    if RUNTIME_PLAN_TOOL_ID not in executor_tools:
        issues.append(_contract_issue(
            where="assembly.plan_and_execute.executor_tools",
            summary="plan_and_execute executor must expose runtime_plan",
            message="The executor updates dynamic plan state through runtime_plan while executing current steps.",
            path="assembly_spec.json",
            expected='executor tool_access.allowed_tool_ids includes "runtime_plan".',
            actual=", ".join(executor_tools) if executor_tools else "<missing>",
            repair_hint='Add "runtime_plan" to executor tool_access.allowed_tool_ids.',
            target_files=["assembly_spec.json"],
            recommended_skill="12-assembly-pattern-system",
        ))
    final_tools = _tool_access_for_node(bindings, node_id="final_answer")
    if final_tools:
        issues.append(_contract_issue(
            where="assembly.plan_and_execute.final_answer_tools",
            summary="plan_and_execute final_answer must not expose tools",
            message="The final_answer node summarizes completed plan state and evidence without additional tool calls.",
            path="assembly_spec.json",
            expected="no tool_access binding for final_answer, or an empty allowed_tool_ids list.",
            actual=", ".join(final_tools),
            repair_hint="Remove final_answer tool_access or clear final_answer allowed_tool_ids.",
            target_files=["assembly_spec.json"],
            recommended_skill="12-assembly-pattern-system",
        ))
    return issues


def _has_binding(bindings: list[Any], *, node_id: str, binding_type: str) -> bool:
    for binding in bindings:
        target = getattr(binding, "target", None)
        if str(getattr(target, "node_id", "") or "") != node_id:
            continue
        if binding.binding_type == binding_type:
            return True
    return False


def _tool_access_for_node(bindings: list[Any], *, node_id: str) -> list[str]:
    ids: list[str] = []
    for binding in bindings:
        if binding.binding_type != "tool_access":
            continue
        target = getattr(binding, "target", None)
        if str(getattr(target, "node_id", "") or "") != node_id:
            continue
        payload = getattr(binding, "payload", None)
        ids.extend(str(item) for item in (getattr(payload, "allowed_tool_ids", []) or []))
    return ids


def _missing_plan_binding_issue(*, node_id: str, binding_type: str) -> PackageValidationIssue:
    return _contract_issue(
        where="assembly.plan_and_execute.binding",
        summary=f"plan_and_execute {node_id} is missing {binding_type} binding",
        message=f"The plan_and_execute pattern requires {node_id} to have a {binding_type} binding.",
        path="assembly_spec.json",
        expected=f"{node_id} has a {binding_type} binding targeting cognitive.answer.",
        actual="missing",
        repair_hint=f"Add a {binding_type} binding for {node_id}.",
        target_files=["assembly_spec.json"],
        recommended_skill="12-assembly-pattern-system",
    )


def _binding_target_issue(
    *,
    index: int,
    binding: Any,
    expected: str,
    actual: str,
    summary: str,
    message: str,
    repair_template: dict[str, Any],
) -> PackageValidationIssue:
    return PackageValidationIssue(
        where="assembly.binding_target",
        summary=summary,
        message=message,
        path="assembly_spec.json",
        expected=expected,
        actual=actual,
        repair_hint="Align binding.target with the selected runtime pattern node table, then rerun create_agent_validate.",
        target_files=["assembly_spec.json"],
        recommended_skill="12-assembly-pattern-system",
        recommended_resources=["examples/assembly_spec.with_tools_and_bindings.json"],
        schema_path="AgentAssemblySpec.bindings.node_bindings[].target",
        invalid_value_path=f"assembly_spec.json:/bindings/node_bindings/{index}/target",
        expected_shape={
            "target": {"node_id": "pattern node id", "impl": "exact impl from selected pattern node"},
        },
        repair_template=repair_template,
        replace_strategy="replace_object",
        details={"binding_id": str(getattr(binding, "binding_id", "") or ""), "binding_type": str(getattr(binding, "binding_type", "") or "")},
    )


def _package_tool_probe_report(
    root: Path,
    package: Any,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    if scope != "full_static":
        return None
    package_result = PackageToolProvider().discover(ToolProviderContext(package_root=root))
    package_tools = {spec.id: spec for spec in package_result.tool_specs}
    if not package_tools:
        return None
    state = _read_probe_state(root)
    latest = state.latest_by_tool()
    current_digest = _package_digest(root)
    issues: list[PackageValidationIssue] = []
    scheduler_tool_ids = set(_scheduler_package_tool_ids(package, package_tools))
    required_tool_ids = sorted(set(package_tools) | scheduler_tool_ids)
    for tool_id in required_tool_ids:
        record = latest.get(tool_id)
        if record is None:
            issues.append(_probe_issue(
                tool_id=tool_id,
                summary=f"package tool {tool_id} has not been probed",
                actual="missing probe evidence",
                repair_hint="Use create_agent_probe_tool(action='inspect'), then create_agent_probe_tool(action='call', tool_id=..., arguments=..., prompt=..., tool_goal=...) with realistic package tool arguments and human-readable probe context.",
            ))
            continue
        if record.package_digest != current_digest:
            issues.append(_probe_issue(
                tool_id=tool_id,
                summary=f"package tool {tool_id} probe is stale",
                actual="probe package digest does not match current package files",
                repair_hint="The package changed after the last probe. Call create_agent_probe_tool again for this tool.",
            ))
            continue
        if record.status != "passed":
            issues.append(_probe_issue(
                tool_id=tool_id,
                summary=f"package tool {tool_id} probe failed",
                actual=f"{record.observation_status} {record.contract_status}: {record.message}",
                repair_hint="Repair the package tool using the probe observation, then run create_agent_probe_tool call again.",
                details=record.model_dump(mode="json"),
            ))
            continue
        if record.probe_kind != "success_path" or record.only_error_handling_verified or not record.tool_returned_business_output:
            issues.append(_probe_issue(
                tool_id=tool_id,
                summary=f"package tool {tool_id} lacks successful-path probe evidence",
                actual=(
                    f"probe_kind={record.probe_kind}, "
                    f"only_error_handling_verified={record.only_error_handling_verified}, "
                    f"tool_returned_business_output={record.tool_returned_business_output}"
                ),
                repair_hint=(
                    "Run create_agent_probe_tool(action='call', tool_id=..., probe_kind='success_path', "
                    "arguments=..., prompt=..., tool_goal=...) with realistic successful-path inputs. "
                    "If no successful input is available, ask the user for the missing resource instead of publishing."
                ),
                details=record.model_dump(mode="json"),
            ))
    if not issues:
        return None
    return _issues_report(
        root,
        issues,
        scope=scope,
        changed_files=changed_files,
        summary="Package tool probe check failed: " + "; ".join(issue.summary for issue in issues[:3]),
    )


def _manifest_asset_index_issues(root: Path, manifest: Any, package_tools: dict[str, Any]) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    expected_tools = {f"tools/{tool_id}/manifest.json" for tool_id in package_tools}
    issues.extend(_asset_index_issues(
        root,
        field_name="tools",
        declared=set(getattr(manifest, "tools", []) or []),
        expected=expected_tools,
        recommended_skill="10-package-tool-system",
    ))
    return issues


def _asset_index_issues(
    root: Path,
    *,
    field_name: str,
    declared: set[str],
    expected: set[str],
    recommended_skill: str,
) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    missing = sorted(expected - declared)
    dangling = sorted(path for path in declared if not (root / path).is_file())
    if missing:
        issues.append(_contract_issue(
            where=f"package_manifest.{field_name}_index",
            summary=f"agent_package.json {field_name} index is missing package assets",
            message=f"Missing {field_name} entries: {missing}",
            path="agent_package.json",
            expected=f"agent_package.json.{field_name} indexes every generated {field_name} asset.",
            actual=", ".join(missing),
            repair_hint=f"Add the missing package-relative asset paths to agent_package.json.{field_name}.",
            target_files=["agent_package.json", *missing],
            recommended_skill=recommended_skill,
        ))
    if dangling:
        issues.append(_contract_issue(
            where=f"package_manifest.{field_name}_index",
            summary=f"agent_package.json {field_name} index references missing files",
            message=f"Dangling {field_name} entries: {dangling}",
            path="agent_package.json",
            expected=f"Every agent_package.json.{field_name} entry exists in the package.",
            actual=", ".join(dangling),
            repair_hint=f"Create the referenced files or remove stale entries from agent_package.json.{field_name}.",
            target_files=["agent_package.json", *dangling],
            recommended_skill=recommended_skill,
        ))
    return issues


def _assembly_tool_issues(package: Any, package_tools: dict[str, Any]) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    assembly_tools = {spec.id: spec for spec in package.assembly_spec.tools}
    for tool_id, package_spec in package_tools.items():
        assembly_spec = assembly_tools.get(tool_id)
        if assembly_spec is None:
            issues.append(_contract_issue(
                where="assembly.tools_index",
                summary=f"assembly_spec.json does not declare package tool {tool_id}",
                message=f"Package tool {tool_id} exists but assembly_spec.tools has no matching ToolSpec.",
                path="assembly_spec.json",
                expected="assembly_spec.tools contains a ToolSpec object for every package tool manifest.",
                actual=f"missing {tool_id}",
                repair_hint="Add the package tool ToolSpec object to assembly_spec.json tools.",
                target_files=["assembly_spec.json", f"tools/{tool_id}/manifest.json"],
                recommended_skill="12-assembly-pattern-system",
            ))
            continue
        mismatches = _tool_spec_mismatches(package_spec, assembly_spec)
        if mismatches:
            issues.append(_contract_issue(
                where="assembly.tools_manifest_mismatch",
                summary=f"assembly ToolSpec for {tool_id} does not match package manifest",
                message=f"Mismatched ToolSpec fields: {', '.join(mismatches)}",
                path="assembly_spec.json",
                expected="assembly_spec.tools ToolSpec fields match tools/<id>/manifest.json.",
                actual=", ".join(mismatches),
                repair_hint="Copy the canonical ToolSpec shape from the package tool manifest into assembly_spec.json.",
                target_files=["assembly_spec.json", f"tools/{tool_id}/manifest.json"],
                recommended_skill="12-assembly-pattern-system",
            ))
    return issues


def _tools_contract_issues(package: Any) -> list[PackageValidationIssue]:
    contract = package.contracts.get("tools")
    if not isinstance(contract, ToolsContract):
        return []
    legal_builtin_ids = set(get_builtin_tool_ids())
    blocked_ids = _manufacturing_tool_ids()
    issues: list[PackageValidationIssue] = []
    for tool_id in contract.config.builtin_tool_ids:
        if tool_id in blocked_ids or tool_id.startswith("create_agent_"):
            issues.append(_contract_issue(
                where="tools_contract.manufacturing_tool",
                summary=f"contracts/tools.json exposes create-agent manufacturing tool {tool_id}",
                message="Produced AgentPackage must not expose create-agent manufacturing tools as runtime builtins.",
                path="contracts/tools.json",
                expected="contracts/tools.json builtin_tool_ids contains only runtime builtin tool ids.",
                actual=tool_id,
                repair_hint="Remove create-agent manufacturing tool ids from contracts/tools.json.",
                target_files=["contracts/tools.json"],
                recommended_skill="09-tools-system",
            ))
        elif tool_id not in legal_builtin_ids:
            issues.append(_contract_issue(
                where="tools_contract.unknown_builtin_tool",
                summary=f"contracts/tools.json references unknown runtime builtin tool {tool_id}",
                message=f"{tool_id} is not an implemented runtime builtin tool.",
                path="contracts/tools.json",
                expected="contracts/tools.json builtin_tool_ids contains implemented runtime builtin tool ids.",
                actual=tool_id,
                repair_hint="Use an implemented runtime builtin tool id or remove the stale builtin reference.",
                target_files=["contracts/tools.json"],
                recommended_skill="09-tools-system",
            ))
    return issues


def _tool_dependency_issues(root: Path, package: Any, package_tools: dict[str, Any]) -> list[PackageValidationIssue]:
    if not package_tools:
        return []
    contract = package.contracts.get("dependencies")
    if not isinstance(contract, DependenciesContract):
        return []
    declared = _declared_requirement_names(contract.config.python_requirements)
    imports_by_tool = _package_tool_external_imports(root=root, tool_ids=set(package_tools))
    issues: list[PackageValidationIssue] = []
    for tool_id, imports in sorted(imports_by_tool.items()):
        missing = sorted(module for module in imports if _normalize_requirement_name(module) not in declared)
        if not missing:
            continue
        source_files = sorted({path for module in missing for path in imports[module]})
        issues.append(_contract_issue(
            where="dependencies.package_tool_imports",
            summary=f"package tool {tool_id} imports undeclared Python dependencies",
            message=(
                f"tools/{tool_id} imports third-party modules not declared in "
                f"contracts/dependencies.json config.python_requirements: {', '.join(missing)}"
            ),
            path="contracts/dependencies.json",
            expected="Every non-stdlib package tool import is declared in dependencies.config.python_requirements.",
            actual=", ".join(missing),
            repair_hint=(
                "Add the required Python distributions to contracts/dependencies.json config.python_requirements. "
                "Use the imported module name as the starting point unless the Python distribution name is known to differ."
            ),
            target_files=["contracts/dependencies.json", *source_files],
            recommended_skill="02-model-system",
            details={
                "tool_id": tool_id,
                "missing_imports": missing,
                "declared_python_requirements": list(contract.config.python_requirements),
                "source_files": source_files,
            },
        ))
    return issues


def _package_tool_external_imports(*, root: Path, tool_ids: set[str]) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    tools_root = root / "tools"
    for tool_id in sorted(tool_ids):
        tool_root = tools_root / tool_id
        if not tool_root.is_dir():
            continue
        for source in sorted(tool_root.glob("**/*.py")):
            modules = _external_imports_for_file(root=root, source=source)
            if not modules:
                continue
            relative = _relative(root, source)
            bucket = result.setdefault(tool_id, {})
            for module in modules:
                bucket.setdefault(module, []).append(relative)
    return result


def _external_imports_for_file(*, root: Path, source: Path) -> set[str]:
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except SyntaxError:
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = _top_level_module(alias.name)
                if _is_external_tool_import(root=root, source=source, module=top):
                    modules.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            top = _top_level_module(node.module or "")
            if _is_external_tool_import(root=root, source=source, module=top):
                modules.add(top)
    return modules


def _top_level_module(value: str) -> str:
    return str(value or "").split(".", 1)[0].strip()


def _is_external_tool_import(*, root: Path, source: Path, module: str) -> bool:
    if not module:
        return False
    if module == "__future__":
        return False
    if module == "agent_factory":
        return False
    if module in sys.builtin_module_names:
        return False
    stdlib_modules = getattr(sys, "stdlib_module_names", set())
    if module in stdlib_modules:
        return False
    if _local_module_exists(root=root, source=source, module=module):
        return False
    return True


def _local_module_exists(*, root: Path, source: Path, module: str) -> bool:
    candidates = [
        source.parent / f"{module}.py",
        source.parent / module / "__init__.py",
        root / f"{module}.py",
        root / module / "__init__.py",
    ]
    return any(candidate.exists() for candidate in candidates)


def _declared_requirement_names(requirements: list[str]) -> set[str]:
    names: set[str] = set()
    for requirement in requirements:
        name = _requirement_name(requirement)
        if name:
            names.add(name)
    return names


def _requirement_name(requirement: str) -> str:
    text = str(requirement or "").strip().split(";", 1)[0].strip()
    if " @ " in text:
        text = text.split(" @ ", 1)[0].strip()
    match = re.match(r"([A-Za-z0-9_.-]+)", text)
    return _normalize_requirement_name(match.group(1)) if match else ""


def _normalize_requirement_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", str(value or "").strip().lower())


def _tool_access_issues(package: Any, package_tools: dict[str, Any], inherited_mcp_tools: set[str]) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    legal_tool_ids = set(get_builtin_tool_ids()) | set(package_tools) | set(inherited_mcp_tools)
    pattern_id = str(getattr(getattr(package.assembly_spec, "runtime", None), "pattern_id", "") or "")
    if pattern_id == PLAN_AND_EXECUTE_PATTERN_ID:
        legal_tool_ids.add(RUNTIME_PLAN_TOOL_ID)
    blocked_ids = _manufacturing_tool_ids()
    for binding in package.assembly_spec.bindings.node_bindings:
        if binding.binding_type != "tool_access":
            continue
        allowed_tool_ids = list(getattr(binding.payload, "allowed_tool_ids", []) or [])
        for tool_id in allowed_tool_ids:
            if tool_id in blocked_ids or tool_id.startswith("create_agent_"):
                issues.append(_contract_issue(
                    where="assembly.tool_access.manufacturing_tool",
                    summary=f"tool_access exposes create-agent manufacturing tool {tool_id}",
                    message="Produced AgentPackage must not expose create-agent manufacturing tools.",
                    path="assembly_spec.json",
                    expected="Only runtime builtin tools, package tools, and inherited MCP tools are exposed to produced agents.",
                    actual=tool_id,
                    repair_hint="Remove create-agent manufacturing tool ids from tool_access allowed_tool_ids.",
                    target_files=["assembly_spec.json"],
                    recommended_skill="12-assembly-pattern-system",
                ))
            elif tool_id not in legal_tool_ids:
                issues.append(_contract_issue(
                    where="assembly.tool_access.unknown_tool",
                    summary=f"tool_access references unknown tool {tool_id}",
                    message=f"{tool_id} is not an implemented runtime builtin tool and not a package tool.",
                    path="assembly_spec.json",
                    expected="tool_access.allowed_tool_ids contains runtime builtin, generated package, or inherited MCP tool ids.",
                    actual=tool_id,
                    repair_hint="Use an implemented runtime builtin tool id, add a package tool manifest with the same id, or reference an available inherited MCP candidate.",
                    target_files=["assembly_spec.json", "contracts/tools.json", "tools/"],
                    recommended_skill="09-tools-system",
                ))
    return issues


def _scheduler_tool_target_issues(package: Any, package_tools: dict[str, Any], inherited_mcp_tools: set[str]) -> list[PackageValidationIssue]:
    issues: list[PackageValidationIssue] = []
    legal_tool_ids = set(get_builtin_tool_ids()) | set(package_tools) | set(inherited_mcp_tools)
    contract = package.contracts.get("scheduler_seed")
    if not isinstance(contract, SchedulerSeedContract):
        return issues
    for seed in contract.config.seeds:
        if seed.target.target_type != "tool_call":
            continue
        tool_id = str(seed.target.payload.get("tool_id") or "").strip()
        if tool_id and tool_id not in legal_tool_ids:
            issues.append(_contract_issue(
                where="scheduler_seed.target_tool",
                summary=f"scheduler seed {seed.seed_id} targets unknown tool {tool_id}",
                message="scheduler_seed tool_call targets must point to an executable runtime builtin, package tool, or inherited MCP tool.",
                path="contracts/scheduler_seed.json",
                expected="scheduler_seed.target.payload.tool_id is executable.",
                actual=tool_id,
                repair_hint="Change the scheduler target to a valid tool id or add the missing package tool.",
                target_files=["contracts/scheduler_seed.json", "tools/"],
                recommended_skill="15-scheduler-seed-system",
            ))
    return issues


def _scheduler_package_tool_ids(package: Any, package_tools: dict[str, Any]) -> list[str]:
    contract = package.contracts.get("scheduler_seed")
    if not isinstance(contract, SchedulerSeedContract):
        return []
    ids: list[str] = []
    for seed in contract.config.seeds:
        if seed.target.target_type == "tool_call":
            tool_id = str(seed.target.payload.get("tool_id") or "").strip()
            if tool_id in package_tools:
                ids.append(tool_id)
    return ids


def _tool_spec_mismatches(left: Any, right: Any) -> list[str]:
    left_payload = left.model_dump(mode="json") if hasattr(left, "model_dump") else dict(left)
    right_payload = right.model_dump(mode="json") if hasattr(right, "model_dump") else dict(right)
    keys = ("description", "entrypoint", "input_schema", "output_schema", "resources", "risk_level", "concurrent")
    return [key for key in keys if left_payload.get(key) != right_payload.get(key)]


def _manufacturing_tool_ids() -> set[str]:
    return {
        "create_agent_control",
        "create_agent_stage",
        "create_agent_probe_tool",
        "create_agent_publish",
        "skill",
    }


def _inherited_mcp_tool_ids() -> set[str]:
    try:
        return factory_mcp_tool_ids()
    except Exception:
        return set()


def _read_probe_state(root: Path) -> PackageToolProbeState:
    path = root / ".factory" / "tool_probe.json"
    if not path.is_file():
        return PackageToolProbeState()
    try:
        return PackageToolProbeState.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return PackageToolProbeState()


def _package_digest(root: Path) -> str:
    fingerprint: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        parts = relative.split("/")
        if not relative or parts[0] == ".factory" or "__pycache__" in parts or relative.endswith(".pyc") or relative == ".DS_Store":
            continue
        fingerprint[relative] = sha256(path.read_bytes()).hexdigest()
    return sha256(json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _contract_issue(
    *,
    where: str,
    summary: str,
    message: str,
    path: str,
    expected: str,
    actual: str,
    repair_hint: str,
    target_files: list[str],
    recommended_skill: str,
    details: dict[str, Any] | None = None,
) -> PackageValidationIssue:
    return PackageValidationIssue(
        where=where,
        summary=summary,
        message=message,
        path=path,
        expected=expected,
        actual=actual,
        repair_hint=repair_hint,
        target_files=target_files,
        recommended_skill=recommended_skill,
        details=details or {},
    )


def _probe_issue(
    *,
    tool_id: str,
    summary: str,
    actual: str,
    repair_hint: str,
    details: dict[str, Any] | None = None,
) -> PackageValidationIssue:
    return _contract_issue(
        where="package_tool_probe",
        summary=summary,
        message=summary,
        path=f"tools/{tool_id}",
        expected="Generated package tools have fresh successful-path create_agent_probe_tool evidence before publish.",
        actual=actual,
        repair_hint=repair_hint,
        target_files=[f"tools/{tool_id}/manifest.json", f"tools/{tool_id}/tool.py", "assembly_spec.json"],
        recommended_skill="10-package-tool-system",
        details=details,
    )


def _issues_report(
    root: Path,
    issues: list[PackageValidationIssue],
    *,
    scope: ValidationScope,
    changed_files: list[str],
    summary: str,
) -> PackageValidationReport:
    target_files = sorted({target for issue in issues for target in issue.target_files})
    repair_bundle = REPAIR_POLICY.generic_bundle(
        where=issues[0].where if issues else "package_file_contract",
        target_files=target_files,
        exc=ValueError(summary),
    )
    return _with_scope(
        PackageValidationReport(
            package_root=str(root),
            summary=summary,
            issues=[
                issue if issue.repair_bundle is not None else issue.model_copy(update={"repair_bundle": repair_bundle})
                for issue in issues
            ],
        ),
        scope=scope,
        changed_files=changed_files,
    )


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name

def _exception_details(exc: Exception) -> dict[str, Any]:
    return {"exception_type": type(exc).__name__}


def _semantic_completeness_report(
    root: Path,
    package: Any,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    """Check that the package has actual logic, not just empty scaffold defaults."""
    issues: list[PackageValidationIssue] = []

    bindings = package.assembly_spec.bindings
    bindings_dict = bindings.model_dump(mode="json") if hasattr(bindings, "model_dump") else (dict(bindings) if bindings else {})
    has_bindings = any(v for v in bindings_dict.values() if v)
    if not has_bindings:
        issues.append(PackageValidationIssue(
            where="semantic.bindings_empty",
            summary="assembly_spec has empty bindings",
            message="The assembly must bind model and tool services to function.",
            path="assembly_spec.json",
            expected="assembly_spec.bindings with model and/or tool service bindings",
            actual="bindings are empty or all null",
            repair_hint="Add model_service and tool_service bindings in assembly_spec.json. Load skill 12-assembly-pattern-system.",
            target_files=["assembly_spec.json"],
            recommended_skill="12-assembly-pattern-system",
        ))

    if not issues:
        return None

    target_files = sorted({f for issue in issues for f in issue.target_files})
    repair_bundle = REPAIR_POLICY.generic_bundle(
        where="semantic_completeness",
        target_files=target_files,
        exc=ValueError("; ".join(issue.summary for issue in issues)),
    )
    return _with_scope(
        PackageValidationReport(
            package_root=str(root),
            summary="Semantic completeness check failed: " + "; ".join(issue.summary for issue in issues[:3]),
            issues=[
                issue if issue.repair_bundle is not None else issue.model_copy(update={"repair_bundle": repair_bundle})
                for issue in issues
            ],
        ),
        scope=scope,
        changed_files=changed_files,
    )
