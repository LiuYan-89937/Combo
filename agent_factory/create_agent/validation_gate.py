from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from agent_factory.create_agent.models import (
    PackageValidationNextAction,
    PackageValidationReport,
    PackageValidationState,
)
from agent_factory.create_agent.validator import CreateAgentPackageValidator, ValidationScope
from agent_factory.create_agent.workspace import CreateAgentWorkspace


@dataclass(frozen=True, slots=True)
class ValidationDecision:
    force_full: bool = False
    requested_scope: str = ""


@dataclass(slots=True)
class CreateAgentValidationGate:
    validator: CreateAgentPackageValidator

    def run(self, workspace: CreateAgentWorkspace, *, decision: ValidationDecision | None = None) -> PackageValidationReport:
        decision = decision or ValidationDecision()
        current_fingerprint = _package_fingerprint(workspace.root)
        previous_state = workspace.read_validation_state()
        previous_report = workspace.read_validation()
        changed_files = _changed_files(previous_state.package_fingerprint if previous_state else {}, current_fingerprint)

        active = workspace.read_system_state().active_stage()
        active_focus_id = active.system_id if active else ""
        scope = _scope_for_focus(active.validation_focus if active else "", force_full=decision.force_full)
        if (
            not decision.force_full
            and previous_state is not None
            and previous_report is not None
            and not changed_files
            and previous_state.active_focus_id == active_focus_id
            and _scope_covers(previous_state.validation_scope, scope)
        ):
            return _cached_report(previous_report, requested_scope=scope, active_focus_id=active_focus_id, workspace=workspace)
        report = self.validator.validate(workspace.root, scope=scope, changed_files=changed_files)
        workspace.write_validation_state(
            PackageValidationState(
                package_fingerprint=current_fingerprint,
                validation_scope=report.validation_scope,
                active_focus_id=active_focus_id,
                updated_at=datetime.now(UTC).isoformat(),
            )
        )
        return report


def _cached_report(
    report: PackageValidationReport,
    *,
    requested_scope: str,
    active_focus_id: str,
    workspace: CreateAgentWorkspace,
) -> PackageValidationReport:
    next_action = PackageValidationNextAction(
        kind="continue" if requested_scope != "full_static" else ("finalize_ready" if report.status == "passed" else "repair_files"),
        target_files=_target_files(report),
        recommended_skill=report.next_action.recommended_skill,
        recommended_resources=report.next_action.recommended_resources,
        repair_bundles=report.next_action.repair_bundles,
    )
    summary = report.summary or "No package-relevant changes since the previous validation."
    if active_focus_id == "capability_implementation" and report.status == "passed":
        summary = _capability_cached_summary(workspace)
    return report.model_copy(
        update={
            "validation_scope": requested_scope,
            "changed_files": [],
            "cached": True,
            "skipped": True,
            "summary": summary,
            "next_action": next_action,
        }
    )


def _target_files(report: PackageValidationReport) -> list[str]:
    values: list[str] = []
    for issue in report.issues:
        values.extend(issue.target_files)
    return sorted(set(values))


def _capability_cached_summary(workspace: CreateAgentWorkspace) -> str:
    if _baseline_only_package(workspace.root):
        return (
            "Baseline empty AgentPackage is valid. Continue capability implementation from the user request: "
            "read at most one relevant capability example, edit package capability files, then stop for validation."
        )
    return (
        "Capability package files have not changed since the previous validation. Continue implementation or move focus based on "
        "the requested behavior; do not audit scaffold files."
    )


def _baseline_only_package(root: Path) -> bool:
    generated_dirs = ("tools", "nodes", "knowledge", "prompts", "patterns", "policies", "strategies", "formatters")
    for relative in generated_dirs:
        directory = root / relative
        if directory.is_dir() and any(item.is_file() for item in directory.rglob("*")):
            return False
    return True


def _scope_for_focus(validation_scope: str, *, force_full: bool) -> ValidationScope:
    if force_full:
        return "full_static"
    if validation_scope in {"full_static", "assembly_compile", "package_shape", "python_syntax", "runtime_contract_build"}:
        return validation_scope
    if validation_scope in {
        "runtime_contract_build_subset",
        "tools_contract_validate",
        "render_manifest_validate",
        "scheduler_seed_validate",
    }:
        return "runtime_contract_build"
    if validation_scope == "package_tool_syntax_and_binding":
        return "python_syntax"
    return "workspace_hygiene"


def _scope_covers(previous_scope: str, requested_scope: str) -> bool:
    if previous_scope == requested_scope:
        return True
    if previous_scope == "full_static":
        return True
    if requested_scope == "workspace_hygiene":
        return previous_scope in {
            "package_shape",
            "runtime_contract_build",
            "assembly_compile",
            "python_syntax",
            "full_static",
        }
    return False


def _changed_files(previous: dict[str, str], current: dict[str, str]) -> list[str]:
    paths = set(previous) | set(current)
    return sorted(path for path in paths if previous.get(path) != current.get(path))


def _package_fingerprint(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    fingerprint: dict[str, str] = {}
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if _ignore_path(relative):
            continue
        fingerprint[relative] = sha256(path.read_bytes()).hexdigest()
    return fingerprint


def _ignore_path(relative: str) -> bool:
    parts = relative.split("/")
    return (
        not relative
        or parts[0] == ".factory"
        or "__pycache__" in parts
        or relative.endswith(".pyc")
        or relative == ".DS_Store"
    )
