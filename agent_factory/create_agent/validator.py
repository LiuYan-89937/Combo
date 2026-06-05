from __future__ import annotations

import json
from pathlib import Path
import py_compile
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML

from agent_factory.create_agent.smoke_test import run_smoke_test
from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.create_agent.repair_policy import CreateAgentRepairPolicy
from agent_factory.create_agent.models import (
    PackageValidationIssue,
    PackageValidationNextAction,
    PackageValidationReport,
)
from agent_factory.create_agent.runtime_path_repair import find_runtime_path_repairs
from agent_factory.package_runtime import register_package_patterns
from agent_factory.runtime_contracts import AgentPackageLoader, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_contracts.schema import REQUIRED_AGENT_PACKAGE_CONTRACTS
from agent_factory.runtime_kernel.kernel import RuntimeKernelFacade
from agent_factory.runtime_kernel.persistence import LangGraphCheckpointerConfig, LangGraphStoreConfig
from agent_factory.tooling.skills.schema import SkillGatewayState


ValidationScope = str
REPAIR_POLICY = CreateAgentRepairPolicy()


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
                    next_action=PackageValidationNextAction(
                        kind="repair_files",
                        target_files=["agent_package.json"],
                        recommended_skill=repair_bundle.recommended_skill,
                        recommended_resources=repair_bundle.recommended_resources,
                        repair_bundles=[repair_bundle],
                    ),
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

        try:
            package = AgentPackageLoader().load_path(manifest_path)
        except Exception as exc:
            return _failed(root, "package.load", exc, ["agent_package.json"], scope=scope, changed_files=changed)
        runtime_path_report = _runtime_path_report(root, package, scope=scope, changed_files=changed)
        if runtime_path_report is not None:
            return runtime_path_report
        if scope == "package_shape":
            return _passed(root, scope=scope, changed_files=changed, summary="Package shape checks passed.")
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
            return _failed(root, "runtime_contracts.build", exc, ["agent_package.json", "contracts"], scope=scope, changed_files=changed)
        if scope == "runtime_contract_build":
            return _passed(root, scope=scope, changed_files=changed, summary="Runtime contract build checks passed.")
        try:
            register_package_patterns(facade=compiler.facade, package=package, runtime_build=runtime_build)
            compiler.compile(package.assembly_spec, runtime_build=runtime_build)
        except Exception as exc:
            return _failed(root, "assembly.compile", exc, ["assembly_spec.json", "patterns", "bindings"], scope=scope, changed_files=changed)
        if scope != "full_static":
            return _passed(root, scope=scope, changed_files=changed, summary="Assembly compile checks passed.")
        # Full static: semantic completeness gate
        semantic_report = _semantic_completeness_report(root, package, scope=scope, changed_files=changed)
        if semantic_report is not None:
            return semantic_report
        # Full static: smoke test gate
        smoke_report = _smoke_test_report(root, package, scope=scope, changed_files=changed)
        if smoke_report is not None:
            return smoke_report
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
        next_action=PackageValidationNextAction(kind="finalize_ready" if scope == "full_static" else "continue"),
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
        next_action=PackageValidationNextAction(
            kind="repair_files",
            target_files=target_files,
            recommended_skill=repair_bundle.recommended_skill,
            recommended_resources=repair_bundle.recommended_resources,
            repair_bundles=[repair_bundle],
        ),
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
        repair_hint="Apply the deterministic package scaffold repair for required built-in contracts, then rerun validation.",
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
            next_action=PackageValidationNextAction(
                kind="repair_files",
                target_files=target_files,
                recommended_skill=repair_bundle.recommended_skill,
                recommended_resources=repair_bundle.recommended_resources,
                repair_bundles=[repair_bundle],
            ),
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
            next_action=PackageValidationNextAction(
                kind="repair_files",
                target_files=target_files,
                recommended_skill=bundles[0].recommended_skill,
                recommended_resources=bundles[0].recommended_resources,
                repair_bundles=bundles,
            ),
            issues=issues,
        ),
        scope=scope,
        changed_files=changed_files,
    )


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
                next_action=PackageValidationNextAction(
                    kind="repair_files",
                    target_files=[relative],
                    recommended_skill=repair_bundle.recommended_skill,
                    recommended_resources=repair_bundle.recommended_resources,
                    repair_bundles=[repair_bundle],
                ),
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
                    next_action=PackageValidationNextAction(
                        kind="repair_files",
                        target_files=[relative_path],
                        recommended_skill=repair_bundle.recommended_skill,
                        recommended_resources=repair_bundle.recommended_resources,
                        repair_bundles=[repair_bundle],
                    ),
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
                    next_action=PackageValidationNextAction(
                        kind="repair_files",
                        target_files=[relative_path],
                        recommended_skill=repair_bundle.recommended_skill,
                        recommended_resources=repair_bundle.recommended_resources,
                        repair_bundles=[repair_bundle],
                    ),
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
                next_action=PackageValidationNextAction(
                    kind="repair_files",
                    target_files=[relative],
                    recommended_skill=repair_bundle.recommended_skill,
                    recommended_resources=repair_bundle.recommended_resources,
                    repair_bundles=[repair_bundle],
                ),
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

    # Check 1: Pattern has real nodes (not just ingress→finalize)
    for pattern in package.patterns:
        nodes = pattern.nodes if hasattr(pattern, "nodes") else []
        node_types = set()
        for node in nodes:
            if hasattr(node, "type"):
                node_types.add(str(node.type))
            elif isinstance(node, dict):
                node_types.add(str(node.get("type", "")))
        non_terminal_types = node_types - {"reserved", "terminal"}
        if not non_terminal_types and len(nodes) <= 2:
            issues.append(PackageValidationIssue(
                where="semantic.pattern_logic",
                summary=f"Pattern '{pattern.pattern_id}' only has ingress→finalize with no operational logic",
                message="The pattern must include cognitive or operational nodes (e.g. tool_call, answer, route) to be functional.",
                path="patterns/main.yaml",
                expected="Pattern with >2 nodes including at least one cognitive or operational node",
                actual=f"Pattern has {len(nodes)} nodes, types: {sorted(node_types)}",
                repair_hint="Add operational.tool_call and cognitive.answer nodes to the pattern. Load skill 13-assembly-and-patterns for guidance.",
                target_files=["patterns/main.yaml", "assembly_spec.json"],
                recommended_skill="13-assembly-and-patterns",
            ))
            break

    # Check 2: Assembly bindings non-empty
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
            repair_hint="Add model_service and tool_service bindings in assembly_spec.json. Load skill 13-assembly-and-patterns.",
            target_files=["assembly_spec.json"],
            recommended_skill="13-assembly-and-patterns",
        ))

    # Check 4: If user requested scheduling, scheduler_seed must exist
    request_path = root / ".factory" / "request.txt"
    if request_path.exists():
        request_text = request_path.read_text(encoding="utf-8").lower()
        schedule_keywords = {"定时", "每天", "每日", "推送", "schedule", "cron", "daily", "periodic"}
        if any(kw in request_text for kw in schedule_keywords):
            # Check scheduler_seed contract exists and has actual jobs
            scheduler_seed = package.contracts.get("scheduler_seed") or {}
            seed_plans = scheduler_seed.get("config", {}).get("seeds", [])
            if not seed_plans:
                issues.append(PackageValidationIssue(
                    where="semantic.scheduler_seed_missing",
                    summary="User requested scheduled behavior but no scheduler_seed jobs are defined",
                    message="The user's request mentions timed/scheduled behavior. scheduler_seed_contract must define at least one cron job.",
                    path="contracts/scheduler_seed.json" if (root / "contracts" / "scheduler_seed.json").exists() else "agent_package.json",
                    expected="scheduler_seed_contract with at least one seed plan (cron job)",
                    actual="No scheduler seed plans found",
                    repair_hint="Create contracts/scheduler_seed.json with cron-triggered jobs. Load skill 12-scheduler-seeds for schema and examples.",
                    target_files=["contracts/scheduler_seed.json" if (root / "contracts" / "scheduler_seed.json").exists() else "agent_package.json"],
                    recommended_skill="12-scheduler-seeds",
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
            next_action=PackageValidationNextAction(
                kind="repair_files",
                target_files=target_files,
                recommended_skill=issues[0].recommended_skill,
                recommended_resources=issues[0].recommended_resources,
                repair_bundles=[repair_bundle],
            ),
            issues=issues,
        ),
        scope=scope,
        changed_files=changed_files,
    )


def _smoke_test_report(
    root: Path,
    package: Any,
    *,
    scope: ValidationScope,
    changed_files: list[str],
) -> PackageValidationReport | None:
    """Run the manufactured agent with task_model to verify it produces useful output."""
    try:
        result = run_smoke_test(root)
    except Exception as exc:
        repair_bundle = REPAIR_POLICY.generic_bundle(
            where="smoke_test.runtime",
            target_files=["assembly_spec.json", "patterns/main.yaml"],
            exc=exc,
        )
        return _with_scope(
            PackageValidationReport(
                package_root=str(root),
                summary=f"Smoke test crashed: {type(exc).__name__}: {exc}",
                next_action=PackageValidationNextAction(
                    kind="repair_files",
                    target_files=["assembly_spec.json", "patterns/main.yaml"],
                    recommended_skill="13-assembly-and-patterns",
                    repair_bundles=[repair_bundle],
                ),
                issues=[
                    PackageValidationIssue(
                        where="smoke_test.runtime",
                        summary=f"Smoke test crashed: {type(exc).__name__}",
                        message=str(exc),
                        path="assembly_spec.json",
                        expected="Agent runs without crashing on a test message",
                        actual=f"{type(exc).__name__}: {exc}",
                        repair_hint="Fix the runtime error. Check pattern nodes, bindings, and tool entrypoints.",
                        target_files=["assembly_spec.json", "patterns/main.yaml"],
                        recommended_skill="13-assembly-and-patterns",
                        details=_exception_details(exc),
                    )
                ],
            ),
            scope=scope,
            changed_files=changed_files,
        )

    if result.passed:
        return None

    error_summary = "; ".join(result.errors[:3]) if result.errors else "Agent produced no useful output"
    repair_bundle = REPAIR_POLICY.generic_bundle(
        where="smoke_test.quality",
        target_files=["patterns/main.yaml", "contracts/tools.json"],
        exc=ValueError(error_summary),
    )
    return _with_scope(
        PackageValidationReport(
            package_root=str(root),
            summary=f"Smoke test failed: {error_summary}",
            next_action=PackageValidationNextAction(
                kind="repair_files",
                target_files=["patterns/main.yaml", "contracts/tools.json", "assembly_spec.json"],
                recommended_skill="13-assembly-and-patterns",
                repair_bundles=[repair_bundle],
            ),
            issues=[
                PackageValidationIssue(
                    where="smoke_test.quality",
                    summary="Agent failed smoke test",
                    message=f"Test input: {result.test_input!r}. Errors: {error_summary}. Tools called: {result.tool_calls_observed}. Final answer: {result.final_answer!r}",
                    path="patterns/main.yaml",
                    expected="Agent produces a non-empty final_answer and invokes declared tools",
                    actual=f"final_answer={result.final_answer!r}, tools={result.tool_calls_observed}, errors={result.errors}",
                    repair_hint="Ensure the pattern routes to tool_call and answer nodes. Verify tools are correctly bound and produce output. Check model bindings.",
                    target_files=["patterns/main.yaml", "contracts/tools.json", "assembly_spec.json"],
                    recommended_skill="13-assembly-and-patterns",
                )
            ],
        ),
        scope=scope,
        changed_files=changed_files,
    )
