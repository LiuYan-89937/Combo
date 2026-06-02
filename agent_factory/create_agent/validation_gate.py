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


@dataclass(slots=True)
class CreateAgentValidationGate:
    validator: CreateAgentPackageValidator

    def run(self, workspace: CreateAgentWorkspace, *, decision: ValidationDecision | None = None) -> PackageValidationReport:
        decision = decision or ValidationDecision()
        current_fingerprint = _package_fingerprint(workspace.root)
        previous_state = workspace.read_validation_state()
        previous_report = workspace.read_validation()
        changed_files = _changed_files(previous_state.package_fingerprint if previous_state else {}, current_fingerprint)
        if not decision.force_full and previous_state is not None and previous_report is not None and not changed_files:
            return _cached_report(previous_report)

        scope = "full_static" if decision.force_full else _validation_scope(changed_files, previous_state is None)
        report = self.validator.validate(workspace.root, scope=scope, changed_files=changed_files)
        workspace.write_validation_state(
            PackageValidationState(
                package_fingerprint=current_fingerprint,
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
            ),
        }
    )


def _target_files(report: PackageValidationReport) -> list[str]:
    values: list[str] = []
    for issue in report.issues:
        values.extend(issue.target_files)
    return sorted(set(values))


def _validation_scope(changed_files: list[str], first_validation: bool) -> ValidationScope:
    if first_validation:
        return "full_static"
    if not changed_files:
        return "workspace_hygiene"
    if any(path.endswith(".py") and (path.startswith("tools/") or path.startswith("nodes/")) for path in changed_files):
        return "full_static"
    if any(path == "assembly_spec.json" or path.startswith("patterns/") or path.startswith("bindings/") for path in changed_files):
        return "assembly_compile"
    if any(path == "agent_package.json" or path.startswith("contracts/") for path in changed_files):
        return "runtime_contract_build"
    if any(path.endswith((".json", ".yaml", ".yml")) for path in changed_files):
        return "package_shape"
    return "workspace_hygiene"


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
