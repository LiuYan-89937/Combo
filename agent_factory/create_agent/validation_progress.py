from __future__ import annotations

from datetime import UTC, datetime

from agent_factory.create_agent.models import (
    PackageValidationReport,
    SystemManufacturingState,
    SystemRepairIssue,
    SystemStage,
    SystemStageStatus,
    SystemStageValidation,
)


def validation_event_from_tool_calls(tool_calls: list[dict[str, object]]) -> str:
    tool_names = {str(call.get("name") or "") for call in tool_calls}
    if "create_agent_control" in tool_names:
        return "control"
    if "create_agent_validate" in tool_names:
        return "explicit_validation"
    if tool_names & {"write", "edit", "multi_edit"}:
        return "package_change"
    return "none"


def stage_progress_summary(
    before: SystemManufacturingState,
    after: SystemManufacturingState,
    report: PackageValidationReport,
) -> dict[str, object]:
    before_active = before.active_stage()
    after_active = after.active_stage()
    return {
        "validation_status": report.status,
        "previous_active_system": before_active.system_id if before_active else "",
        "previous_active_status": before_active.status.value if before_active else "",
        "current_active_system": after_active.system_id if after_active else "",
        "current_active_status": after_active.status.value if after_active else "",
        "advanced": bool(
            report.status == "passed"
            and before_active is not None
            and (
                after_active is None
                or after_active.system_id != before_active.system_id
            )
        ),
    }


def apply_system_validation_progress(
    state: SystemManufacturingState,
    report: PackageValidationReport,
) -> SystemManufacturingState:
    stage = state.active_stage()
    if stage is None:
        return state
    if report.status == "passed":
        return _mark_stage_done(state, stage, report)
    return _mark_stage_failed(state, stage, report)


def _mark_stage_done(
    state: SystemManufacturingState,
    stage: SystemStage,
    report: PackageValidationReport,
) -> SystemManufacturingState:
    resolved_repairs = [
        item.model_copy(update={"resolved": True})
        for item in stage.repair_history
    ]
    updated = stage.model_copy(
        update={
            "status": SystemStageStatus.done,
            "repair_history": resolved_repairs,
            "validation": SystemStageValidation(
                scope=report.validation_scope,
                status="passed",
                summary=report.summary,
                issue_ids=[],
                updated_at=datetime.now(UTC).isoformat(),
            ),
        }
    )
    return state.update_stage(updated)


def _mark_stage_failed(
    state: SystemManufacturingState,
    stage: SystemStage,
    report: PackageValidationReport,
) -> SystemManufacturingState:
    existing = {item.issue_id: item for item in stage.repair_history}
    repairs = list(stage.repair_history)
    for issue in report.issues:
        digest = issue.to_digest()
        if digest.issue_id in existing:
            continue
        repairs.append(
            SystemRepairIssue(
                issue_id=digest.issue_id,
                where=issue.where,
                summary=issue.summary,
                category=_issue_category(issue.where, issue.message),
                target_files=issue.target_files,
                repair_hint=issue.repair_hint,
            )
        )
    updated = stage.model_copy(
        update={
            "status": SystemStageStatus.failed_needs_repair,
            "repair_history": repairs,
            "validation": SystemStageValidation(
                scope=report.validation_scope,
                status="failed",
                summary=report.summary,
                issue_ids=[issue.to_digest().issue_id for issue in report.issues],
                updated_at=datetime.now(UTC).isoformat(),
            ),
        }
    )
    return state.update_stage(updated)


def _issue_category(where: str, message: str) -> str:
    text = f"{where} {message}".lower()
    if "attributeerror" in text or "adapter" in text or "validator" in text:
        return "validator_runtime_defect"
    if "resource" in text:
        return "resource_missing"
    if "tool" in text:
        return "tool_binding_error"
    if "assembly" in text or "pattern" in text:
        return "assembly_compile_error"
    if "contract" in text:
        return "runtime_contract_error"
    if "schema" in text or "validationerror" in text:
        return "schema_error"
    return "package_shape_error"
