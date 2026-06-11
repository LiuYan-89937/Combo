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
        scope = _scope_for_focus(active.validation_focus if active else "", force_full=decision.force_full)
        if (
            not decision.force_full
            and previous_state is not None
            and previous_report is not None
            and not changed_files
            and _scope_covers(previous_state.validation_scope, scope)
        ):
            return _cached_report(previous_report)
        report = self.validator.validate(workspace.root, scope=scope, changed_files=changed_files)
        workspace.write_validation_state(
            PackageValidationState(
                package_fingerprint=current_fingerprint,
                validation_scope=report.validation_scope,
                updated_at=datetime.now(UTC).isoformat(),
            )
        )
        return report


def _cached_report(report: PackageValidationReport) -> PackageValidationReport:
    return report.model_copy(
        update={
            "validation_scope": "unchanged",
            "changed_files": [],
            "cached": True,
            "skipped": True,
            "summary": report.summary or "No package-relevant changes since the previous validation.",
            "next_action": PackageValidationNextAction(
                kind="finalize_ready" if report.status == "passed" else "repair_files",
                target_files=_target_files(report),
                recommended_skill=report.next_action.recommended_skill,
                recommended_resources=report.next_action.recommended_resources,
                repair_bundles=report.next_action.repair_bundles,
            ),
        }
    )


def _target_files(report: PackageValidationReport) -> list[str]:
    values: list[str] = []
    for issue in report.issues:
        values.extend(issue.target_files)
    return sorted(set(values))


def _scope_for_focus(validation_scope: str, *, force_full: bool) -> ValidationScope:
    if force_full:
        return "full_static"
    if validation_scope in {"full_static", "assembly_compile", "package_shape", "python_syntax"}:
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
