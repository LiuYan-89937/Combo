from __future__ import annotations

from typing import Annotated, Any, TypedDict
import operator


class FactoryGraphState(TypedDict, total=False):
    requirement: str
    current_stage: str
    status: str
    stage_log: Annotated[list[dict[str, Any]], operator.add]
    requirement_brief: dict[str, Any]
    requirement_understanding: dict[str, Any]
    capability_plan: dict[str, Any]
    condition_report: dict[str, Any]
    resource_need_plan: dict[str, Any]
    evidence_bundle: dict[str, Any]
    resource_contracts: dict[str, Any]
    readiness_decision: dict[str, Any]
    assembly_plan: dict[str, Any]
    package_specs: dict[str, Any]
    tool_packages: dict[str, Any]
    harness_report: dict[str, Any]
    harness_scenarios: list[dict[str, Any]]
    build_summary: dict[str, Any]
    assembly_spec: dict[str, Any]
    errors: Annotated[list[dict[str, Any]], operator.add]
