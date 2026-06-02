from __future__ import annotations

import json
from pathlib import Path
import py_compile
from typing import Any

from ruamel.yaml import YAML

from agent_factory.assembly.compiler import AgentAssemblyCompiler
from agent_factory.create_agent.models import PackageValidationIssue, PackageValidationNextAction, PackageValidationReport
from agent_factory.runtime_contracts import AgentPackageLoader, RuntimeBuildPlanner
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry


ValidationScope = str


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
            return _with_scope(
                PackageValidationReport(
                package_root=str(root),
                summary="agent_package.json is missing.",
                next_action=PackageValidationNextAction(
                    kind="repair_files",
                    target_files=["agent_package.json"],
                    recommended_skill="01-package-manifest",
                    recommended_resources=_recommended_resources("package.manifest", ["agent_package.json"]),
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
                        recommended_skill="01-package-manifest",
                        recommended_resources=_recommended_resources("package.manifest", ["agent_package.json"]),
                    )
                ],
                ),
                scope=scope,
                changed_files=changed,
            )
        try:
            package = AgentPackageLoader().load_path(manifest_path)
        except Exception as exc:
            return _failed(root, "package.load", exc, ["agent_package.json"], scope=scope, changed_files=changed)
        if scope == "package_shape":
            return _passed(root, scope=scope, changed_files=changed, summary="Package shape checks passed.")
        if scope in {"python_syntax", "full_static"}:
            syntax_report = _python_syntax(root, changed)
            if syntax_report is not None:
                return _with_scope(syntax_report, scope=scope, changed_files=changed)
        try:
            compiler = AgentAssemblyCompiler()
            runtime_build = RuntimeBuildPlanner(registry=default_runtime_contract_registry()).build(
                package,
                base_services=compiler.facade.instance.services,
            )
        except Exception as exc:
            return _failed(root, "runtime_contracts.build", exc, ["agent_package.json", "contracts"], scope=scope, changed_files=changed)
        if scope == "runtime_contract_build":
            return _passed(root, scope=scope, changed_files=changed, summary="Runtime contract build checks passed.")
        try:
            compiler.compile(package.assembly_spec, runtime_build=runtime_build)
        except Exception as exc:
            return _failed(root, "assembly.compile", exc, ["assembly_spec.json", "patterns", "bindings"], scope=scope, changed_files=changed)
        return _passed(root, scope=scope, changed_files=changed, summary="Package static validation passed.")


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
    recommended_skill = _recommended_skill(where, target_files)
    recommended_resources = _recommended_resources(where, target_files)
    return PackageValidationReport(
        package_root=str(root),
        validation_scope=scope,  # type: ignore[arg-type]
        changed_files=changed_files,
        summary=f"{where} failed: {type(exc).__name__}: {exc}",
        next_action=PackageValidationNextAction(
            kind="repair_files",
            target_files=target_files,
            recommended_skill=recommended_skill,
            recommended_resources=recommended_resources,
        ),
        issues=[
            PackageValidationIssue(
                where=where,
                summary=f"{type(exc).__name__}: {exc}",
                message=str(exc),
                path=target_files[0] if target_files else "",
                expected=_expected_for_where(where),
                actual=f"{type(exc).__name__}: {exc}",
                repair_hint=_repair_hint(where),
                target_files=target_files,
                recommended_skill=recommended_skill,
                recommended_resources=recommended_resources,
                details=_exception_details(exc),
            )
        ],
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
            return PackageValidationReport(
                package_root=str(root),
                summary=f"{relative} is not parseable: {type(exc).__name__}: {exc}",
                next_action=PackageValidationNextAction(
                    kind="repair_files",
                    target_files=[relative],
                    recommended_skill=_recommended_skill("workspace_hygiene.parse", [relative]),
                    recommended_resources=_recommended_resources("workspace_hygiene.parse", [relative]),
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
                        recommended_skill=_recommended_skill("workspace_hygiene.parse", [relative]),
                        recommended_resources=_recommended_resources("workspace_hygiene.parse", [relative]),
                        details=_exception_details(exc),
                    )
                ],
            )
    return None


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
            recommended_resources = _recommended_resources("python_syntax.compile", [relative])
            return PackageValidationReport(
                package_root=str(root),
                summary=f"{relative} failed Python syntax validation: {type(exc).__name__}: {exc}",
                next_action=PackageValidationNextAction(
                    kind="repair_files",
                    target_files=[relative],
                    recommended_skill="09-package-tools",
                    recommended_resources=recommended_resources,
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
                        recommended_skill="09-package-tools",
                        recommended_resources=recommended_resources,
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


def _expected_for_where(where: str) -> str:
    return {
        "package.load": "AgentPackageLoader can load agent_package.json and referenced package files.",
        "runtime_contracts.build": "RuntimeBuildPlanner can build all declared RuntimeContracts.",
        "assembly.compile": "AgentAssemblyCompiler can compile the declared assembly and patterns.",
    }.get(where, "validation check passes")


def _repair_hint(where: str) -> str:
    return {
        "package.load": "Repair manifest paths and package structure, then rerun package validation.",
        "runtime_contracts.build": "Repair contract schema or required contract files using the relevant contract skill.",
        "assembly.compile": "Repair assembly, patterns, node impl ids, bindings, or state references.",
    }.get(where, "Repair the target files indicated by the validation issue.")


def _recommended_skill(where: str, target_files: list[str]) -> str:
    targets = " ".join(target_files)
    if where == "runtime_contracts.build":
        return "02-runtime-contract-index"
    if where == "assembly.compile":
        return "13-assembly-and-patterns"
    if "tools/" in targets:
        return "09-package-tools"
    if "nodes/" in targets:
        return "10-package-nodes"
    return "01-package-manifest"


def _recommended_resources(where: str, target_files: list[str]) -> list[str]:
    skill = _recommended_skill(where, target_files)
    targets = " ".join(target_files)
    if skill == "01-package-manifest":
        return [
            "references/agent_package.schema.json",
            "examples/agent_package.minimal.json",
            "references/agent_package.repair_hints.md",
        ]
    if skill == "02-runtime-contract-index":
        return [
            "references/runtime_contract_index.repair_hints.md",
            "examples/runtime_contract_index.minimal.json",
        ]
    if skill == "09-package-tools":
        artifact = "package_tool" if "tools/" in targets else "tool_contract"
        return [
            f"references/{artifact}.schema.json",
            f"examples/{artifact}.minimal.json",
            f"references/{artifact}.repair_hints.md",
        ]
    if skill == "10-package-nodes":
        return [
            "references/package_node.schema.json",
            "examples/package_node.minimal.json",
            "references/package_node.repair_hints.md",
        ]
    if skill == "13-assembly-and-patterns":
        return [
            "references/assembly_spec.schema.json",
            "examples/assembly_spec.minimal.json",
            "references/pattern.schema.json",
            "references/assembly_spec.repair_hints.md",
        ]
    return ["references/contract.repair_hints.md"]


def _exception_details(exc: Exception) -> dict[str, Any]:
    return {"exception_type": type(exc).__name__}
