from __future__ import annotations

from typing import Literal

from agent_factory.factory_runtime.production.state import FactoryProductionStateDict


def route_after_intent_classification(
    state: FactoryProductionStateDict,
) -> Literal["analyze_requirement", "needs_clarification", "not_agent_request"]:
    intent_payload = state.get("factory_intent") or {}
    intent = intent_payload.get("intent") if isinstance(intent_payload, dict) else None
    if intent == "create_agent_clear":
        return "analyze_requirement"
    if intent == "create_agent_unclear":
        return "needs_clarification"
    return "not_agent_request"


def route_after_maybe_clarify(
    state: FactoryProductionStateDict,
) -> Literal["needs_clarification", "plan_capability_preconditions"]:
    if state.get("clarification_questions"):
        return "needs_clarification"
    return "plan_capability_preconditions"


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


def route_after_verification(
    state: FactoryProductionStateDict,
) -> Literal["continue", "failed"]:
    if state.get("error") is None:
        return "continue"
    return "failed"


def route_after_tool_tests(
    state: FactoryProductionStateDict,
) -> Literal["continue", "repair_tool_tests", "failed"]:
    if state.get("error") is None:
        return "continue"
    error = state.get("error")
    code = error.get("code") if isinstance(error, dict) else getattr(error, "code", None)
    if (
        code == "generated_tool_tests_failed"
        and state.get("tool_test_repair_attempts", 0)
        < state.get("max_tool_test_repair_attempts", 1)
    ):
        return "repair_tool_tests"
    return "failed"


def route_after_tool_test_repair(
    state: FactoryProductionStateDict,
) -> Literal["run_generated_tool_tests", "failed"]:
    if state.get("error") is None:
        return "run_generated_tool_tests"
    if state.get("package_path") is not None:
        return "run_generated_tool_tests"
    return "failed"


def route_after_validate_primitives(
    state: FactoryProductionStateDict,
) -> Literal["repair_primitives", "write_package", "failed"]:
    if state.get("primitives") is not None and state.get("error") is None:
        return "write_package"
    if state.get("repair_attempts", 0) < state.get("max_repair_attempts", 1):
        return "repair_primitives"
    return "failed"


def route_after_readiness(
    state: FactoryProductionStateDict,
) -> Literal["plan_primitives", "needs_clarification", "failed"]:
    if state.get("error") is not None:
        return "failed"
    readiness_decision = state.get("readiness_decision")
    decision_status = None
    if isinstance(readiness_decision, dict):
        decision_status = readiness_decision.get("status")
    elif readiness_decision is not None:
        decision_status = getattr(readiness_decision, "status", None)
    if decision_status in {"ready", "ready_with_deferred"}:
        return "plan_primitives"
    if decision_status == "needs_user_input":
        return "needs_clarification"
    if decision_status == "blocked":
        return "failed"
    readiness = state.get("readiness_report")
    status = None
    if isinstance(readiness, dict):
        status = readiness.get("status")
    elif readiness is not None:
        status = getattr(readiness, "status", None)
    if status in {"ready", "mock_only_allowed"}:
        return "plan_primitives"
    if status == "needs_user_input":
        return "needs_clarification"
    return "failed"


def route_after_repair(
    state: FactoryProductionStateDict,
) -> Literal["validate_primitives", "failed"]:
    if state.get("raw_model_data") is not None and state.get("error") is None:
        return "validate_primitives"
    return "failed"


def route_after_validate_package(
    state: FactoryProductionStateDict,
) -> Literal["static_check_tool_scripts", "failed"]:
    report = state.get("validation_report")
    report_ok = _validation_report_ok(report, ignore_files={"mcp.yaml", "harness.yaml"})
    if report is not None and report_ok and state.get("error") is None:
        return "static_check_tool_scripts"
    return "failed"


def _validation_report_ok(report: object, *, ignore_files: set[str] | None = None) -> bool:
    ignore_files = ignore_files or set()
    if report is None:
        return False
    if not isinstance(report, dict):
        issues = getattr(report, "issues", [])
        for issue in issues:
            severity = getattr(issue, "severity", None)
            file = getattr(issue, "file", None)
            if severity in {"error", "fatal"} and file not in ignore_files:
                return False
        return True
    issues = report.get("issues") or []
    for issue in issues:
        severity = issue.get("severity") if isinstance(issue, dict) else getattr(issue, "severity", None)
        file = issue.get("file") if isinstance(issue, dict) else getattr(issue, "file", None)
        if severity in {"error", "fatal"} and file not in ignore_files:
            return False
    return True
