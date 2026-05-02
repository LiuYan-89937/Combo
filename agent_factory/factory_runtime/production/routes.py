from __future__ import annotations

from typing import Literal

from agent_factory.factory_runtime.production.state import FactoryProductionStateDict


def route_after_maybe_clarify(
    state: FactoryProductionStateDict,
) -> Literal["needs_clarification", "plan_primitives"]:
    if state.get("clarification_questions"):
        return "needs_clarification"
    return "plan_primitives"


def route_after_plan_primitives(
    state: FactoryProductionStateDict,
) -> Literal["validate_primitives", "failed"]:
    if state.get("error") is not None and state.get("raw_model_data") is None:
        return "failed"
    return "validate_primitives"


def route_after_package_write(
    state: FactoryProductionStateDict,
) -> Literal["generate_tool_scripts", "failed"]:
    if state.get("package_path") is not None and state.get("error") is None:
        return "generate_tool_scripts"
    return "failed"


def route_after_artifact_generation(
    state: FactoryProductionStateDict,
) -> Literal["continue", "failed"]:
    if state.get("error") is None:
        return "continue"
    return "failed"


def route_after_validate_primitives(
    state: FactoryProductionStateDict,
) -> Literal["repair_primitives", "write_package", "failed"]:
    if state.get("primitives") is not None and state.get("error") is None:
        return "write_package"
    if state.get("repair_attempts", 0) < state.get("max_repair_attempts", 1):
        return "repair_primitives"
    return "failed"


def route_after_repair(
    state: FactoryProductionStateDict,
) -> Literal["validate_primitives", "failed"]:
    if state.get("raw_model_data") is not None and state.get("error") is None:
        return "validate_primitives"
    return "failed"


def route_after_validate_package(
    state: FactoryProductionStateDict,
) -> Literal["record_factory_memory", "failed"]:
    report = state.get("validation_report")
    report_ok = _validation_report_ok(report)
    if report is not None and report_ok and state.get("error") is None:
        return "record_factory_memory"
    return "failed"


def _validation_report_ok(report: object) -> bool:
    if report is None:
        return False
    if not isinstance(report, dict):
        return bool(getattr(report, "ok", False))
    issues = report.get("issues") or []
    for issue in issues:
        severity = issue.get("severity") if isinstance(issue, dict) else getattr(issue, "severity", None)
        if severity in {"error", "fatal"}:
            return False
    return True
