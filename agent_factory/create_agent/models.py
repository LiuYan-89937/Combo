from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SYSTEM_STATE_FILE = ".factory/system_state.json"
ACTION_FILE = ".factory/action.json"
VALIDATION_FILE = ".factory/validation.json"
VALIDATION_STATE_FILE = ".factory/validation_state.json"
RESOURCES_FILE = ".factory/resources.json"
SKILL_GATEWAY_STATE_FILE = ".factory/skill_gateway_state.json"
TEXT_SUMMARY_LIMIT = 240


class ResourceFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    value: Any = None
    secret: bool = False
    source: Literal["user", "tool", "mcp", "skill", "default", "system"] = "user"
    confidence: float = 1.0
    evidence_refs: list[str] = Field(default_factory=list)


class CreateAgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["continue", "ask_user", "finalize"] = "continue"
    message: str = ""
    resource_facts: list[ResourceFact] = Field(default_factory=list)


class CreateAgentIntentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["manufacture_agent", "workspace_assist", "chat"]
    rationale: str = ""


class SystemStageStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    validating = "validating"
    done = "done"
    failed_needs_repair = "failed_needs_repair"
    blocked_waiting_user = "blocked_waiting_user"


class SystemRepairIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str
    where: str
    summary: str
    category: Literal[
        "schema_error",
        "package_shape_error",
        "runtime_contract_error",
        "assembly_compile_error",
        "tool_binding_error",
        "model_behavior_error",
        "resource_missing",
        "resource_unavailable",
        "validator_runtime_defect",
    ] = "schema_error"
    target_files: list[str] = Field(default_factory=list)
    repair_hint: str = ""
    resolved: bool = False


class SystemStageValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: str
    status: Literal["not_run", "passed", "failed"] = "not_run"
    summary: str = ""
    issue_ids: list[str] = Field(default_factory=list)
    updated_at: str = ""


class SystemStageHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outputs: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class SystemStage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_id: str
    stage_order: int
    title: str
    status: SystemStageStatus = SystemStageStatus.pending
    focus_files: list[str] = Field(default_factory=list)
    suggested_skills: list[str] = Field(default_factory=list)
    validation_focus: str = "workspace_hygiene"
    focus_summary: str = ""
    repair_history: list[SystemRepairIssue] = Field(default_factory=list)
    handoff_outputs: SystemStageHandoff = Field(default_factory=SystemStageHandoff)
    validation: SystemStageValidation | None = None

    def to_digest(self) -> dict[str, Any]:
        return {
            "system_id": self.system_id,
            "stage_order": self.stage_order,
            "title": self.title,
            "status": self.status.value,
            "focus_files": self.focus_files,
            "suggested_skills": self.suggested_skills,
            "validation_focus": self.validation_focus,
            "focus_summary": self.focus_summary,
            "open_issues": [
                issue.model_dump(mode="json")
                for issue in self.repair_history
                if not issue.resolved
            ][:6],
        }


class SystemManufacturingState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["system_manufacturing_state.v0"] = "system_manufacturing_state.v0"
    stages: list[SystemStage] = Field(default_factory=list)
    active_focus_id: str = ""
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def active_stage(self) -> SystemStage | None:
        if self.active_focus_id:
            for stage in self.stages:
                if stage.system_id == self.active_focus_id:
                    return stage
        return None

    def all_done(self) -> bool:
        active = self.active_stage()
        return active is not None and active.system_id == "validation_publish"

    def update_stage(self, updated_stage: SystemStage) -> "SystemManufacturingState":
        stages = [
            updated_stage if stage.system_id == updated_stage.system_id else stage
            for stage in self.stages
        ]
        return self.model_copy(
            update={
                "stages": stages,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )

    def set_focus(self, focus_id: str, *, status: SystemStageStatus = SystemStageStatus.in_progress) -> "SystemManufacturingState":
        target = str(focus_id or "").strip()
        if not target:
            raise ValueError("focus_id must not be empty")
        found = False
        stages: list[SystemStage] = []
        for stage in self.stages:
            if stage.system_id == target:
                stages.append(stage.model_copy(update={"status": status}))
                found = True
            else:
                stages.append(stage)
        if not found:
            raise ValueError(f"unknown create-agent focus_id: {focus_id}")
        return self.model_copy(
            update={
                "stages": stages,
                "active_focus_id": target,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )

    def working_set(self) -> dict[str, Any]:
        active = self.active_stage()
        return {
            "active_focus": active.to_digest() if active else None,
            "remaining": sum(1 for stage in self.stages if stage.status != SystemStageStatus.done),
            "total": len(self.stages),
            "stages": [stage.to_digest() for stage in self.stages],
        }


class PackageRepairTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_key: str = ""
    target_file: str
    recommended_skill: str = ""
    recommended_resources: list[str] = Field(default_factory=list)


class PackageRepairBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    kind: Literal[
        "manifest_missing",
        "missing_required_contracts",
        "missing_referenced_files",
        "runtime_path_contract_repair",
        "runtime_contract_build",
        "assembly_compile",
        "python_syntax",
        "generic_repair",
    ]
    repair_action: Literal[
        "materialize_base_package",
        "materialize_required_contracts",
        "normalize_runtime_contract_paths",
        "read_skill_resources",
        "repair_files",
        "fix_python_syntax",
    ]
    machine_applicable: bool = False
    target_files: list[str] = Field(default_factory=list)
    targets: list[PackageRepairTarget] = Field(default_factory=list)
    recommended_skill: str = ""
    recommended_resources: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


class PackageValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    where: str
    summary: str
    message: str
    severity: Literal["blocking", "warning", "info"] = "blocking"
    path: str = ""
    expected: str = ""
    actual: str = ""
    repair_hint: str = ""
    target_files: list[str] = Field(default_factory=list)
    recommended_skill: str = ""
    recommended_resources: list[str] = Field(default_factory=list)
    repair_bundle: PackageRepairBundle | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    def repair_issue_id(self) -> str:
        return self.to_digest().repair_issue_id()

    def to_digest(self) -> "ValidationIssueDigest":
        raw = json.dumps(
            {
                "where": self.where,
                "path": self.path,
                "target_files": self.target_files,
                "recommended_skill": self.recommended_skill,
                "summary": self.summary,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        issue_id = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return ValidationIssueDigest(
            issue_id=issue_id,
            where=self.where,
            summary=_compact_text(self.summary, TEXT_SUMMARY_LIMIT),
            severity=self.severity,
            path=self.path,
            expected=_compact_text(self.expected, TEXT_SUMMARY_LIMIT),
            actual=_compact_text(self.actual, TEXT_SUMMARY_LIMIT),
            repair_hint=_compact_text(self.repair_hint, TEXT_SUMMARY_LIMIT),
            target_files=self.target_files[:8],
            recommended_skill=self.recommended_skill,
            recommended_resources=self.recommended_resources[:8],
        )


class ValidationIssueDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str
    where: str
    summary: str
    severity: Literal["blocking", "warning", "info"] = "blocking"
    path: str = ""
    expected: str = ""
    actual: str = ""
    repair_hint: str = ""
    target_files: list[str] = Field(default_factory=list)
    recommended_skill: str = ""
    recommended_resources: list[str] = Field(default_factory=list)

    def repair_issue_id(self) -> str:
        return f"repair_{self.issue_id}"


class PackageValidationNextAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["continue", "repair_files", "ask_user", "finalize_ready"] = "continue"
    target_files: list[str] = Field(default_factory=list)
    recommended_skill: str = ""
    recommended_resources: list[str] = Field(default_factory=list)
    repair_bundles: list[PackageRepairBundle] = Field(default_factory=list)


class PackageValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_validation_report.v0"] = "package_validation_report.v0"
    status: Literal["passed", "failed"] = "failed"
    package_root: str
    validation_scope: Literal[
        "workspace_hygiene",
        "package_shape",
        "runtime_contract_build",
        "assembly_compile",
        "python_syntax",
        "full_static",
        "unchanged",
    ] = "full_static"
    changed_files: list[str] = Field(default_factory=list)
    cached: bool = False
    skipped: bool = False
    summary: str = ""
    next_action: PackageValidationNextAction = Field(default_factory=PackageValidationNextAction)
    issues: list[PackageValidationIssue] = Field(default_factory=list)

    def to_digest(self) -> "PackageValidationDigest":
        return PackageValidationDigest(
            status=self.status,
            package_root=self.package_root,
            validation_scope=self.validation_scope,
            changed_files=self.changed_files[:12],
            cached=self.cached,
            skipped=self.skipped,
            summary=_compact_text(self.summary, TEXT_SUMMARY_LIMIT),
            next_action=self.next_action,
            issues=[issue.to_digest() for issue in self.issues[:8]],
        )


class PackageValidationDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_validation_digest.v0"] = "package_validation_digest.v0"
    status: Literal["passed", "failed"] = "failed"
    package_root: str
    validation_scope: Literal[
        "workspace_hygiene",
        "package_shape",
        "runtime_contract_build",
        "assembly_compile",
        "python_syntax",
        "full_static",
        "unchanged",
    ] = "full_static"
    changed_files: list[str] = Field(default_factory=list)
    cached: bool = False
    skipped: bool = False
    summary: str = ""
    next_action: PackageValidationNextAction = Field(default_factory=PackageValidationNextAction)
    issues: list[ValidationIssueDigest] = Field(default_factory=list)


class PackageValidationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["package_validation_state.v0"] = "package_validation_state.v0"
    package_fingerprint: dict[str, str] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def initial_system_manufacturing_state() -> SystemManufacturingState:
    stages = [
        _stage(
            "requirement_focus",
            1,
            "Requirement focus",
            [RESOURCES_FILE, "agent_package.json"],
            ["00-manufacturing-control", "01-package-identity-system", "05-resources-system"],
            "workspace_hygiene",
            "Clarify user intent, missing resources, secrets, schedules, and manufacturable capability boundaries.",
        ),
        _stage(
            "package_foundation",
            2,
            "Package foundation",
            ["agent_package.json", "resources.json", "render_manifest.json", "sandbox_contract.json"],
            ["01-package-identity-system", "05-resources-system", "13-render-event-system"],
            "package_shape",
            "Stabilize package manifest shape, root references, basic resources, render, and sandbox files.",
        ),
        _stage(
            "runtime_contracts",
            3,
            "Runtime contracts",
            ["contracts/"],
            [
                "02-model-system",
                "03-session-system",
                "04-state-system",
                "06-context-system",
                "07-memory-system",
                "08-knowledge-system",
                "09-tools-system",
                "14-scheduler-system",
            ],
            "runtime_contract_build",
            "Declare and validate the runtime contracts needed by the produced AgentPackage.",
        ),
        _stage(
            "capability_implementation",
            4,
            "Capability implementation",
            ["tools/", "nodes/", "contracts/tools.json", "contracts/node_provider.json", "contracts/scheduler_seed.json", "resources.json"],
            ["09-tools-system", "10-package-tool-system", "11-node-provider-system", "15-scheduler-seed-system", "08-knowledge-system"],
            "runtime_contract_build",
            "Connect requested capabilities to executable package tools, nodes, scheduler seeds, knowledge, or resources.",
        ),
        _stage(
            "experience_and_operations",
            5,
            "Experience and operations",
            ["assembly_spec.json", "patterns/", "render_manifest.json", "contracts/render.json", "contracts/trace.json", "contracts/artifact.json"],
            ["12-assembly-pattern-system", "13-render-event-system", "16-trace-artifact-system"],
            "assembly_compile",
            "Assemble runtime behavior, render/session experience, events, and operational trace artifacts.",
        ),
        _stage(
            "validation_publish",
            6,
            "Validation and publish",
            [],
            ["17-final-validation-repair", "00-manufacturing-control"],
            "full_static",
            "Run full validation, repair from evidence, and finalize only when the package is ready.",
        ),
    ]
    started = stages[0].model_copy(update={"status": SystemStageStatus.in_progress})
    return SystemManufacturingState(stages=[started, *stages[1:]], active_focus_id=started.system_id)


def _stage(
    system_id: str,
    stage_order: int,
    title: str,
    focus_files: list[str],
    suggested_skills: list[str],
    validation_focus: str,
    focus_summary: str,
) -> SystemStage:
    return SystemStage(
        system_id=system_id,
        stage_order=stage_order,
        title=title,
        focus_files=focus_files,
        suggested_skills=suggested_skills,
        validation_focus=validation_focus,
        focus_summary=focus_summary,
    )


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}…"


def _compact_issue_details(details: dict[str, Any]) -> dict[str, Any]:
    where = str(details.get("where") or "")
    summary = _compact_text(details.get("summary") or details.get("message") or where, TEXT_SUMMARY_LIMIT)
    target_files = details.get("target_files")
    if not isinstance(target_files, list):
        target_files = []
    recommended_resources = details.get("recommended_resources")
    if not isinstance(recommended_resources, list):
        recommended_resources = []
    issue_id = str(details.get("issue_id") or "")
    if not issue_id:
        raw = json.dumps(
            {
                "where": where,
                "path": details.get("path") or "",
                "target_files": target_files,
                "recommended_skill": details.get("recommended_skill") or "",
                "summary": summary,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        issue_id = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return {
        "issue_id": issue_id,
        "where": where,
        "summary": summary,
        "repair_hint": _compact_text(details.get("repair_hint") or "", TEXT_SUMMARY_LIMIT),
        "target_files": [str(item) for item in target_files[:8]],
        "recommended_skill": str(details.get("recommended_skill") or ""),
        "recommended_resources": [str(item) for item in recommended_resources[:8]],
    }
