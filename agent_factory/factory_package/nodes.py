from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_factory.factory_package.capability_contract import (
    capability_contract_catalog_payload,
    capability_contract_message,
    validate_capability_contract,
    validation_feedback_text as capability_validation_feedback_text,
)
from agent_factory.factory_package.constants import (
    CAPABILITY_CONTRACT_NODE_ID,
    PACKAGE_BUILD_NODE_ID,
    PRODUCT_BRIEF_NODE_ID,
    RUNTIME_DESIGN_NODE_ID,
    TOOL_MANUFACTURING_NODE_ID,
)
from agent_factory.factory_package.model_call import FactoryModelCallError, call_structured_model
from agent_factory.factory_package.package_build import (
    build_agent_package,
    default_package_build_plan,
    merge_package_build_plan,
    package_build_message,
)
from agent_factory.factory_package.runtime_design import (
    runtime_design_message,
    runtime_kernel_catalog_payload,
    validate_runtime_design,
    validation_feedback_text,
)
from agent_factory.factory_package.schemas import (
    CapabilityContractOutput,
    CapabilityContractValidationReport,
    PackageBuildModelPlan,
    PackageBuildPlan,
    ProductBriefOutput,
    RuntimeDesignOutput,
    RuntimeDesignValidationReport,
    ToolBindingSmokePlan,
    ToolDesign,
    ToolImplementationDraft,
    ToolManufacturingCheck,
    ToolManufacturingOutput,
    ToolManufacturingReport,
    ToolSourceDecisionOutput,
    ToolSpecDraft,
    ToolUnitTestPlan,
)
from agent_factory.factory_package.tool_manufacturing import (
    approved_package_tool_plans,
    default_tool_manufacturing_output,
    finalize_tool_manufacturing_output,
    persist_tool_manufacturing_report,
    run_generated_tool_pipeline,
    tool_manufacturing_catalog_payload,
    tool_manufacturing_message,
)
from agent_factory.prompts import PromptId, output_json_schema
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.node_providers import StaticNodeProvider
from agent_factory.runtime_kernel.state import RuntimeState


FACTORY_MANUFACTURING_NAMESPACE = "factory_manufacturing"
FACTORY_NODE_PROVIDER_ID = "builtin.factory_manufacturing_nodes"
_STATE_KEYS = {
    "factory_run_id",
    "input_intent",
    "force_manufacture",
    "interaction_mode",
    "current_node",
    "status",
    "graph_control",
    "model_activity",
    "manufacturing_log",
    "product_brief",
    "runtime_design",
    "runtime_design_validation",
    "capability_contract",
    "capability_contract_validation",
    "tool_manufacturing",
    "tool_manufacturing_report",
    "package_build_plan",
    "package_build_report",
    "factory_response",
    "errors",
}
RUNTIME_DESIGN_VALIDATION_ATTEMPTS = 3
CAPABILITY_CONTRACT_VALIDATION_ATTEMPTS = 3
TOOL_MANUFACTURING_TOOL_REPAIR_ATTEMPTS = 3


def factory_manufacturing_node_provider() -> StaticNodeProvider:
    return StaticNodeProvider(
        provider_id=FACTORY_NODE_PROVIDER_ID,
        nodes=(
            FactoryProductBriefNode(),
            FactoryRuntimeDesignNode(),
            FactoryCapabilityContractNode(),
            FactoryToolManufacturingNode(),
            FactoryPackageBuildNode(),
        ),
    )


@dataclass(frozen=True, slots=True)
class FactoryProductBriefNode:
    node_type = "cognitive"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"package_state", "conversation", "execution", "observability"}

    @property
    def impl_id(self) -> str:
        return f"builtin.factory.{PRODUCT_BRIEF_NODE_ID}"

    def execute(self, state: RuntimeState, _context: NodeExecutionContext) -> dict[str, Any]:
        namespace_state = _initial_state(state)
        try:
            brief = call_structured_model(
                stage_id=PRODUCT_BRIEF_NODE_ID,
                prompt_id=PromptId.PRODUCT_BRIEF_DRAFT,
                output_model=ProductBriefOutput,
                values={
                    "user_input": namespace_state.get("input_intent") or "",
                    "current_product_brief": namespace_state.get("product_brief") or {},
                    "output_json_schema": output_json_schema(ProductBriefOutput),
                },
            )
        except FactoryModelCallError as exc:
            next_state = {
                **namespace_state,
                "current_node": PRODUCT_BRIEF_NODE_ID,
                "status": "failed",
                "errors": [
                    *list(namespace_state.get("errors") or []),
                    {"where": PRODUCT_BRIEF_NODE_ID, "message": str(exc)},
                ],
            }
            return {
                "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
                "execution": {
                    "current_node": PRODUCT_BRIEF_NODE_ID,
                    "finished": True,
                    "finish_status": "failed",
                    "route_decision": "execution.finished",
                    "last_error": str(exc),
                    "last_error_location": PRODUCT_BRIEF_NODE_ID,
                },
            }

        brief_payload = brief.model_dump(mode="json")
        final_answer = _product_brief_message(brief)
        ready_for_runtime_design = brief.ready_for_runtime_design and not brief.blocking_questions
        next_state = {
            **namespace_state,
            "current_node": PRODUCT_BRIEF_NODE_ID,
            "status": "product_brief_ready" if ready_for_runtime_design else "product_brief_needs_input",
            "product_brief": brief_payload,
            "factory_response": {"message": final_answer},
            "manufacturing_log": [
                *list(namespace_state.get("manufacturing_log") or []),
                {
                    "node_id": PRODUCT_BRIEF_NODE_ID,
                    "status": "completed",
                    "message": _log_message(brief),
                },
            ],
        }
        return {
            "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
            "conversation": {"final_answer": final_answer},
            "execution": {
                "current_node": PRODUCT_BRIEF_NODE_ID,
                "finished": not ready_for_runtime_design,
                "finish_status": "completed" if not ready_for_runtime_design else None,
                "route_decision": "execution.finished" if not ready_for_runtime_design else None,
            },
        }


@dataclass(frozen=True, slots=True)
class FactoryRuntimeDesignNode:
    node_type = "cognitive"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"package_state", "conversation", "execution", "observability"}

    @property
    def impl_id(self) -> str:
        return f"builtin.factory.{RUNTIME_DESIGN_NODE_ID}"

    def execute(self, state: RuntimeState, _context: NodeExecutionContext) -> dict[str, Any]:
        namespace_state = _initial_state(state)
        product_brief = dict(namespace_state.get("product_brief") or {})
        if not product_brief:
            return _runtime_design_failed_patch(
                namespace_state=namespace_state,
                message="Runtime Design requires product_brief.v0 before it can run.",
            )

        report: RuntimeDesignValidationReport | None = None
        design: RuntimeDesignOutput | None = None
        try:
            for _attempt in range(1, RUNTIME_DESIGN_VALIDATION_ATTEMPTS + 1):
                design = call_structured_model(
                    stage_id=RUNTIME_DESIGN_NODE_ID,
                    prompt_id=PromptId.RUNTIME_DESIGN_DRAFT,
                    output_model=RuntimeDesignOutput,
                    values={
                        "user_input": namespace_state.get("input_intent") or "",
                        "product_brief": json.dumps(product_brief, ensure_ascii=False, indent=2),
                        "runtime_kernel_catalog": json.dumps(
                            runtime_kernel_catalog_payload(),
                            ensure_ascii=False,
                            indent=2,
                        ),
                        "validation_feedback": validation_feedback_text(report),
                        "output_json_schema": output_json_schema(RuntimeDesignOutput),
                    },
                )
                report = validate_runtime_design(design)
                if report.status == "valid":
                    break
            if design is None or report is None:
                raise FactoryModelCallError("runtime design model returned no design")
            if report.status != "valid":
                raise FactoryModelCallError("; ".join(report.errors) or "runtime design validation failed")
        except FactoryModelCallError as exc:
            return _runtime_design_failed_patch(namespace_state=namespace_state, message=str(exc), report=report)

        design_payload = design.model_dump(mode="json")
        report_payload = report.model_dump(mode="json")
        final_answer = runtime_design_message(design, report)
        next_state = {
            **namespace_state,
            "current_node": RUNTIME_DESIGN_NODE_ID,
            "status": "runtime_design_ready",
            "runtime_design": design_payload,
            "runtime_design_validation": report_payload,
            "factory_response": {"message": final_answer},
            "manufacturing_log": [
                *list(namespace_state.get("manufacturing_log") or []),
                {
                    "node_id": RUNTIME_DESIGN_NODE_ID,
                    "status": "completed",
                    "message": _runtime_design_log_message(design, report),
                },
            ],
        }
        return {
            "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
            "conversation": {"final_answer": final_answer},
            "execution": {
                "current_node": RUNTIME_DESIGN_NODE_ID,
                "finished": False,
                "finish_status": None,
                "route_decision": None,
            },
        }


@dataclass(frozen=True, slots=True)
class FactoryCapabilityContractNode:
    node_type = "cognitive"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"package_state", "conversation", "execution", "observability"}

    @property
    def impl_id(self) -> str:
        return f"builtin.factory.{CAPABILITY_CONTRACT_NODE_ID}"

    def execute(self, state: RuntimeState, _context: NodeExecutionContext) -> dict[str, Any]:
        namespace_state = _initial_state(state)
        product_brief = dict(namespace_state.get("product_brief") or {})
        runtime_design_payload = dict(namespace_state.get("runtime_design") or {})
        runtime_design_validation = dict(namespace_state.get("runtime_design_validation") or {})
        if not runtime_design_payload:
            return _capability_contract_failed_patch(
                namespace_state=namespace_state,
                message="Capability Contract requires runtime_design.v0 before it can run.",
            )
        if runtime_design_validation.get("status") != "valid":
            return _capability_contract_failed_patch(
                namespace_state=namespace_state,
                message="Capability Contract requires a valid Runtime Design.",
            )
        try:
            runtime_design = RuntimeDesignOutput.model_validate(runtime_design_payload)
        except Exception as exc:
            return _capability_contract_failed_patch(
                namespace_state=namespace_state,
                message=f"Runtime Design payload is invalid: {exc}",
            )

        report: CapabilityContractValidationReport | None = None
        contract: CapabilityContractOutput | None = None
        try:
            for _attempt in range(1, CAPABILITY_CONTRACT_VALIDATION_ATTEMPTS + 1):
                contract = call_structured_model(
                    stage_id=CAPABILITY_CONTRACT_NODE_ID,
                    prompt_id=PromptId.CAPABILITY_CONTRACT_DRAFT,
                    output_model=CapabilityContractOutput,
                    values={
                        "user_input": namespace_state.get("input_intent") or "",
                        "product_brief": json.dumps(product_brief, ensure_ascii=False, indent=2),
                        "runtime_design": json.dumps(runtime_design_payload, ensure_ascii=False, indent=2),
                        "runtime_design_validation": json.dumps(runtime_design_validation, ensure_ascii=False, indent=2),
                        "capability_contract_catalog": json.dumps(
                            capability_contract_catalog_payload(runtime_design),
                            ensure_ascii=False,
                            indent=2,
                        ),
                        "validation_feedback": capability_validation_feedback_text(report),
                        "output_json_schema": output_json_schema(CapabilityContractOutput),
                    },
                )
                report = validate_capability_contract(contract, runtime_design=runtime_design)
                if report.status == "valid":
                    break
            if contract is None or report is None:
                raise FactoryModelCallError("capability contract model returned no contract")
            if report.status != "valid":
                raise FactoryModelCallError("; ".join(report.errors) or "capability contract validation failed")
        except FactoryModelCallError as exc:
            return _capability_contract_failed_patch(namespace_state=namespace_state, message=str(exc), report=report)

        contract_payload = contract.model_dump(mode="json")
        report_payload = report.model_dump(mode="json")
        final_answer = capability_contract_message(contract, report)
        next_state = {
            **namespace_state,
            "current_node": CAPABILITY_CONTRACT_NODE_ID,
            "status": "capability_contract_ready",
            "capability_contract": contract_payload,
            "capability_contract_validation": report_payload,
            "factory_response": {"message": final_answer},
            "manufacturing_log": [
                *list(namespace_state.get("manufacturing_log") or []),
                {
                    "node_id": CAPABILITY_CONTRACT_NODE_ID,
                    "status": "completed",
                    "message": _capability_contract_log_message(report),
                },
            ],
        }
        return {
            "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
            "conversation": {"final_answer": final_answer},
            "execution": {
                "current_node": CAPABILITY_CONTRACT_NODE_ID,
                "finished": False,
                "finish_status": None,
                "route_decision": None,
            },
        }


@dataclass(frozen=True, slots=True)
class FactoryToolManufacturingNode:
    node_type = "cognitive"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"package_state", "conversation", "execution", "observability"}

    @property
    def impl_id(self) -> str:
        return f"builtin.factory.{TOOL_MANUFACTURING_NODE_ID}"

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        namespace_state = _initial_state(state)
        context.emit_event({"event_type": "tool_manufacturing_started"})
        product_brief_payload = dict(namespace_state.get("product_brief") or {})
        runtime_design_payload = dict(namespace_state.get("runtime_design") or {})
        capability_contract_payload = dict(namespace_state.get("capability_contract") or {})
        capability_contract_validation = dict(namespace_state.get("capability_contract_validation") or {})
        if not capability_contract_payload:
            return _tool_manufacturing_failed_patch(
                namespace_state=namespace_state,
                message="Tool Manufacturing requires capability_contract.v0 before it can run.",
            )
        if capability_contract_validation.get("status") != "valid":
            return _tool_manufacturing_failed_patch(
                namespace_state=namespace_state,
                message="Tool Manufacturing requires a valid Capability Contract.",
            )
        try:
            capability_contract = CapabilityContractOutput.model_validate(capability_contract_payload)
        except Exception as exc:
            return _tool_manufacturing_failed_patch(
                namespace_state=namespace_state,
                message=f"Capability Contract payload is invalid: {exc}",
            )

        output: ToolManufacturingOutput | None = None
        if not capability_contract.tool_specs_to_generate:
            output = default_tool_manufacturing_output(capability_contract)
        else:
            try:
                draft = _draft_tool_manufacturing_output(
                    factory_run_id=str(namespace_state.get("factory_run_id") or ""),
                    product_brief_payload=product_brief_payload,
                    runtime_design_payload=runtime_design_payload,
                    capability_contract_payload=capability_contract_payload,
                    capability_contract=capability_contract,
                )
                output = finalize_tool_manufacturing_output(
                    factory_run_id=str(namespace_state.get("factory_run_id") or ""),
                    output=draft,
                    capability_contract=capability_contract,
                )
                if output.report.status != "valid":
                    raise FactoryModelCallError("; ".join(output.report.errors) or "tool manufacturing validation failed")
            except FactoryModelCallError as exc:
                report = output.report if output is not None else None
                return _tool_manufacturing_failed_patch(namespace_state=namespace_state, message=str(exc), report=report)

        output_payload = output.model_dump(mode="json")
        report_payload = output.report.model_dump(mode="json")
        final_answer = tool_manufacturing_message(output)
        report_paths = persist_tool_manufacturing_report(
            factory_run_id=str(namespace_state.get("factory_run_id") or ""),
            output=output,
        )
        for decision in output.source_decisions:
            context.emit_event(
                {
                    "event_type": "tool_source_decision_completed",
                    "tool_id": decision.tool_id,
                    "source": decision.source,
                    "selected_tool_id": decision.selected_tool_id,
                }
            )
        for design in output.tool_designs:
            context.emit_event({"event_type": "tool_design_completed", "tool_id": design.tool_id})
        for implementation in output.implementations:
            context.emit_event({"event_type": "tool_implementation_completed", "tool_id": implementation.tool_id})
        for check in output.report.checks:
            if check.name.endswith(".dependency_convergence"):
                context.emit_event(
                    {
                        "event_type": "tool_dependency_converged",
                        "status": check.status,
                        "message": check.message,
                        **check.details,
                    }
                )
            elif check.name.endswith(".unit_test_harness") or check.name.endswith(".unit_tests"):
                context.emit_event(
                    {
                        "event_type": "tool_unit_tests_completed",
                        "status": check.status,
                        "message": check.message,
                        **check.details,
                    }
                )
            elif check.name.endswith(".binding_smoke"):
                context.emit_event(
                    {
                        "event_type": "tool_binding_smoke_completed",
                        "status": check.status,
                        "message": check.message,
                    }
                )
        for tool_id in output.report.approved_tool_ids:
            context.emit_event({"event_type": "tool_manufacturing_completed", "tool_id": tool_id})
        if output.report.status != "valid":
            context.emit_event(
                {
                    "event_type": "tool_manufacturing_failed",
                    "errors": list(output.report.errors),
                    "blocked_tool_ids": list(output.report.blocked_tool_ids),
                }
            )
        else:
            context.emit_event(
                {
                    "event_type": "tool_manufacturing_completed",
                    "approved_tool_ids": list(output.report.approved_tool_ids),
                    "decision_count": len(output.source_decisions),
                    "report_paths": report_paths,
                }
            )
        next_state = {
            **namespace_state,
            "current_node": TOOL_MANUFACTURING_NODE_ID,
            "status": "tool_manufacturing_ready",
            "tool_manufacturing": output_payload,
            "tool_manufacturing_report": {**report_payload, "report_paths": report_paths},
            "factory_response": {"message": final_answer},
            "manufacturing_log": [
                *list(namespace_state.get("manufacturing_log") or []),
                {
                    "node_id": TOOL_MANUFACTURING_NODE_ID,
                    "status": "completed",
                    "message": f"Tool Manufacturing approved {len(output.approved_package_tools)} package tool(s).",
                },
            ],
        }
        return {
            "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
            "conversation": {"final_answer": final_answer},
            "execution": {
                "current_node": TOOL_MANUFACTURING_NODE_ID,
                "finished": False,
                "finish_status": None,
                "route_decision": None,
            },
        }


def _draft_tool_manufacturing_output(
    *,
    factory_run_id: str,
    product_brief_payload: dict[str, Any],
    runtime_design_payload: dict[str, Any],
    capability_contract_payload: dict[str, Any],
    capability_contract: CapabilityContractOutput,
) -> ToolManufacturingOutput:
    source_decisions = call_structured_model(
        stage_id=TOOL_MANUFACTURING_NODE_ID,
        prompt_id=PromptId.TOOL_SOURCE_DECISIONS_DRAFT,
        output_model=ToolSourceDecisionOutput,
        values={
            "product_brief": json.dumps(product_brief_payload, ensure_ascii=False, indent=2),
            "runtime_design": json.dumps(runtime_design_payload, ensure_ascii=False, indent=2),
            "capability_contract": json.dumps(capability_contract_payload, ensure_ascii=False, indent=2),
            "tool_catalog": json.dumps(
                tool_manufacturing_catalog_payload(),
                ensure_ascii=False,
                indent=2,
            ),
            "output_json_schema": output_json_schema(ToolSourceDecisionOutput),
        },
    )
    decisions_by_id = {item.tool_id: item for item in source_decisions.source_decisions}
    tool_designs: list[ToolDesign] = []
    tool_specs: list[ToolSpecDraft] = []
    implementations: list[ToolImplementationDraft] = []
    unit_tests: list[ToolUnitTestPlan] = []
    binding_smokes: list[ToolBindingSmokePlan] = []
    approved_tools = []
    pipeline_checks: list[ToolManufacturingCheck] = []
    blocked_tool_ids: list[str] = []
    resource_requirements = json.dumps(
        [item.model_dump(mode="json") for item in capability_contract.resources_required],
        ensure_ascii=False,
        indent=2,
    )

    for requirement in capability_contract.tool_specs_to_generate:
        decision = decisions_by_id.get(requirement.tool_id)
        if decision is None or decision.source != "package_generated":
            continue
        validation_feedback = "No prior validation feedback."
        latest_parts: tuple[ToolDesign, ToolSpecDraft, ToolImplementationDraft, ToolUnitTestPlan, ToolBindingSmokePlan] | None = None
        for _attempt in range(1, TOOL_MANUFACTURING_TOOL_REPAIR_ATTEMPTS + 1):
            parts = _draft_package_generated_tool_parts(
                product_brief_payload=product_brief_payload,
                runtime_design_payload=runtime_design_payload,
                requirement=(
                    json.dumps(requirement.model_dump(mode="json"), ensure_ascii=False, indent=2)
                ),
                decision=json.dumps(decision.model_dump(mode="json"), ensure_ascii=False, indent=2),
                resource_requirements=resource_requirements,
                validation_feedback=validation_feedback,
            )
            latest_parts = parts
            checks, artifact = run_generated_tool_pipeline(
                factory_run_id=factory_run_id,
                tool_id=requirement.tool_id,
                design=parts[0],
                spec=parts[1],
                implementation=parts[2],
                unit_test=parts[3],
                binding_smoke=parts[4],
            )
            pipeline_checks.extend(checks)
            if artifact is not None:
                approved_tools.append(artifact)
                break
            validation_feedback = _tool_manufacturing_feedback_text(checks)
        if latest_parts is not None:
            design, spec, implementation, unit_test, binding_smoke = latest_parts
            tool_designs.append(design)
            tool_specs.append(spec)
            implementations.append(implementation)
            unit_tests.append(unit_test)
            binding_smokes.append(binding_smoke)
        if not any(item.tool_id == requirement.tool_id for item in approved_tools):
            blocked_tool_ids.append(requirement.tool_id)

    return ToolManufacturingOutput(
        source_decisions=source_decisions.source_decisions,
        tool_designs=tool_designs,
        tool_specs=tool_specs,
        implementations=implementations,
        unit_tests=unit_tests,
        binding_smokes=binding_smokes,
        approved_package_tools=approved_tools,
        report=ToolManufacturingReport(
            status="valid" if not blocked_tool_ids else "invalid",
            source_decisions=source_decisions.source_decisions,
            checks=pipeline_checks,
            approved_tool_ids=[item.tool_id for item in approved_tools],
            blocked_tool_ids=blocked_tool_ids,
            errors=[item.message for item in pipeline_checks if item.status == "failed" and item.message] if blocked_tool_ids else [],
        ),
        manufacturing_summary_text=source_decisions.manufacturing_summary_text,
    )


def _draft_package_generated_tool_parts(
    *,
    product_brief_payload: dict[str, Any],
    runtime_design_payload: dict[str, Any],
    requirement: str,
    decision: str,
    resource_requirements: str,
    validation_feedback: str,
) -> tuple[ToolDesign, ToolSpecDraft, ToolImplementationDraft, ToolUnitTestPlan, ToolBindingSmokePlan]:
    common = {
        "product_brief": json.dumps(product_brief_payload, ensure_ascii=False, indent=2),
        "runtime_design": json.dumps(runtime_design_payload, ensure_ascii=False, indent=2),
        "tool_requirement": requirement,
        "source_decision": decision,
        "resource_requirements": resource_requirements,
        "validation_feedback": validation_feedback,
    }
    design = call_structured_model(
        stage_id=TOOL_MANUFACTURING_NODE_ID,
        prompt_id=PromptId.TOOL_DESIGN_DRAFT,
        output_model=ToolDesign,
        values={**common, "output_json_schema": output_json_schema(ToolDesign)},
    )
    spec = call_structured_model(
        stage_id=TOOL_MANUFACTURING_NODE_ID,
        prompt_id=PromptId.TOOL_SPEC_DRAFT,
        output_model=ToolSpecDraft,
        values={
            **common,
            "tool_design": json.dumps(design.model_dump(mode="json"), ensure_ascii=False, indent=2),
            "output_json_schema": output_json_schema(ToolSpecDraft),
        },
    )
    implementation = call_structured_model(
        stage_id=TOOL_MANUFACTURING_NODE_ID,
        prompt_id=PromptId.TOOL_IMPLEMENTATION_DRAFT,
        output_model=ToolImplementationDraft,
        values={
            "tool_design": json.dumps(design.model_dump(mode="json"), ensure_ascii=False, indent=2),
            "tool_spec": json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
            "validation_feedback": validation_feedback,
            "output_json_schema": output_json_schema(ToolImplementationDraft),
        },
    )
    unit_test = call_structured_model(
        stage_id=TOOL_MANUFACTURING_NODE_ID,
        prompt_id=PromptId.TOOL_UNIT_TEST_DRAFT,
        output_model=ToolUnitTestPlan,
        values={
            "tool_design": json.dumps(design.model_dump(mode="json"), ensure_ascii=False, indent=2),
            "tool_spec": json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
            "tool_implementation": json.dumps(implementation.model_dump(mode="json"), ensure_ascii=False, indent=2),
            "validation_feedback": validation_feedback,
            "output_json_schema": output_json_schema(ToolUnitTestPlan),
        },
    )
    binding_smoke = call_structured_model(
        stage_id=TOOL_MANUFACTURING_NODE_ID,
        prompt_id=PromptId.TOOL_BINDING_SMOKE_DRAFT,
        output_model=ToolBindingSmokePlan,
        values={
            "tool_design": json.dumps(design.model_dump(mode="json"), ensure_ascii=False, indent=2),
            "tool_spec": json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
            "tool_implementation": json.dumps(implementation.model_dump(mode="json"), ensure_ascii=False, indent=2),
            "validation_feedback": validation_feedback,
            "output_json_schema": output_json_schema(ToolBindingSmokePlan),
        },
    )
    return design, spec, implementation, unit_test, binding_smoke


def _tool_manufacturing_feedback_text(checks: list[ToolManufacturingCheck]) -> str:
    if not checks:
        return "No validation feedback."
    lines: list[str] = []
    for check in checks:
        if check.status != "failed":
            continue
        lines.append(f"- {check.name}: {check.message}")
        report_path = str(check.details.get("report_path") or "")
        if report_path:
            preview = _read_validation_report_preview(report_path)
            if preview:
                lines.append(preview)
    return "\n".join(lines).strip() or "Previous attempt did not pass validation; regenerate a consistent tool design, implementation, tests, and smoke plan."


def _read_validation_report_preview(path_text: str) -> str:
    try:
        path = Path(path_text)
        if not path.is_file():
            return ""
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    primary_error = str(payload.get("primary_error") or "").strip()
    category = str(payload.get("category") or "").strip()
    stdout = str(payload.get("stdout_preview") or "").strip()
    stderr = str(payload.get("stderr_preview") or "").strip()
    parts = []
    if primary_error:
        prefix = f"{category}: " if category else ""
        parts.append("primary_error:\n" + prefix + primary_error)
    if stdout:
        parts.append("stdout:\n" + stdout[-3000:])
    if stderr:
        parts.append("stderr:\n" + stderr[-3000:])
    return "\n".join(parts)


@dataclass(frozen=True, slots=True)
class FactoryPackageBuildNode:
    node_type = "cognitive"
    supports_interrupt = False
    supports_subgraph_slot = False
    writable_sections = {"package_state", "conversation", "execution", "observability"}

    @property
    def impl_id(self) -> str:
        return f"builtin.factory.{PACKAGE_BUILD_NODE_ID}"

    def execute(self, state: RuntimeState, _context: NodeExecutionContext) -> dict[str, Any]:
        namespace_state = _initial_state(state)
        product_brief_payload = dict(namespace_state.get("product_brief") or {})
        runtime_design_payload = dict(namespace_state.get("runtime_design") or {})
        capability_contract_payload = dict(namespace_state.get("capability_contract") or {})
        capability_contract_validation = dict(namespace_state.get("capability_contract_validation") or {})
        tool_manufacturing_payload = dict(namespace_state.get("tool_manufacturing") or {})
        tool_manufacturing_report = dict(namespace_state.get("tool_manufacturing_report") or {})
        if not capability_contract_payload:
            return _package_build_failed_patch(
                namespace_state=namespace_state,
                message="Package Build requires capability_contract.v0 before it can run.",
            )
        if capability_contract_validation.get("status") != "valid":
            return _package_build_failed_patch(
                namespace_state=namespace_state,
                message="Package Build requires a valid Capability Contract.",
            )
        if not tool_manufacturing_payload:
            return _package_build_failed_patch(
                namespace_state=namespace_state,
                message="Package Build requires tool_manufacturing.v0 before it can run.",
            )
        if tool_manufacturing_report.get("status") != "valid":
            return _package_build_failed_patch(
                namespace_state=namespace_state,
                message="Package Build requires valid Tool Manufacturing output.",
            )
        try:
            product_brief = ProductBriefOutput.model_validate(product_brief_payload)
            runtime_design = RuntimeDesignOutput.model_validate(runtime_design_payload)
            capability_contract = CapabilityContractOutput.model_validate(capability_contract_payload)
            tool_manufacturing = ToolManufacturingOutput.model_validate(tool_manufacturing_payload)
        except Exception as exc:
            return _package_build_failed_patch(
                namespace_state=namespace_state,
                message=f"Package Build inputs are invalid: {exc}",
            )

        approved_tools = approved_package_tool_plans(tool_manufacturing)
        base_plan = default_package_build_plan(
            factory_run_id=str(namespace_state.get("factory_run_id") or ""),
            product_brief=product_brief,
            runtime_design=runtime_design,
            capability_contract=capability_contract,
            approved_package_tools=approved_tools,
        )
        model_plan: PackageBuildModelPlan | None = None
        try:
            model_plan = call_structured_model(
                stage_id=PACKAGE_BUILD_NODE_ID,
                prompt_id=PromptId.PACKAGE_BUILD_DRAFT,
                output_model=PackageBuildModelPlan,
                values={
                    "product_brief": json.dumps(product_brief_payload, ensure_ascii=False, indent=2),
                    "runtime_design": json.dumps(runtime_design_payload, ensure_ascii=False, indent=2),
                    "capability_contract": json.dumps(capability_contract_payload, ensure_ascii=False, indent=2),
                    "tool_manufacturing": json.dumps(tool_manufacturing_payload, ensure_ascii=False, indent=2),
                    "output_json_schema": output_json_schema(PackageBuildModelPlan),
                },
            )
        except FactoryModelCallError:
            model_plan = None

        plan = merge_package_build_plan(base=base_plan, model_plan=model_plan, approved_package_tools=approved_tools)
        result = build_agent_package(
            plan=plan,
            product_brief=product_brief,
            runtime_design=runtime_design,
            capability_contract=capability_contract,
            tool_manufacturing=tool_manufacturing,
        )
        final_answer = package_build_message(result.plan, result.report)
        if result.report.status != "valid":
            return _package_build_failed_patch(
                namespace_state={
                    **namespace_state,
                    "package_build_plan": result.plan.model_dump(mode="json"),
                    "package_build_report": result.report.model_dump(mode="json"),
                },
                message="; ".join(result.report.errors) or "Package Build validation failed.",
            )

        report_payload = result.report.model_dump(mode="json")
        plan_payload = result.plan.model_dump(mode="json")
        next_state = {
            **namespace_state,
            "current_node": PACKAGE_BUILD_NODE_ID,
            "status": "package_build_ready",
            "package_build_plan": plan_payload,
            "package_build_report": report_payload,
            "factory_response": {"message": final_answer},
            "manufacturing_log": [
                *list(namespace_state.get("manufacturing_log") or []),
                {
                    "node_id": PACKAGE_BUILD_NODE_ID,
                    "status": "completed",
                    "message": f"Package Build materialized {len(result.report.materialized_files)} file(s).",
                },
            ],
        }
        return {
            "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
            "conversation": {"final_answer": final_answer},
            "execution": {
                "current_node": PACKAGE_BUILD_NODE_ID,
                "finished": True,
                "finish_status": "completed",
                "route_decision": "execution.finished",
            },
        }


def _initial_state(state: RuntimeState) -> dict[str, Any]:
    raw_existing = dict(state.package_state.get(FACTORY_MANUFACTURING_NAMESPACE) or {})
    existing = {key: value for key, value in raw_existing.items() if key in _STATE_KEYS}
    if not existing.get("factory_run_id"):
        existing["factory_run_id"] = uuid4().hex
    current_input = (state.conversation.current_user_input or "").strip()
    if current_input:
        existing["input_intent"] = current_input
    if current_input and not existing.get("interaction_mode"):
        existing["interaction_mode"] = "create_agent"
    existing.setdefault("model_activity", [])
    existing.setdefault("manufacturing_log", [])
    existing.setdefault("errors", [])
    return existing


def _product_brief_message(brief: ProductBriefOutput) -> str:
    lines = [
        "我先按这个方向制造：",
        "",
        f"目标：{brief.agent_goal or brief.working_title or '待定'}",
        "",
        f"第一版范围：{brief.first_version_scope or '待定'}",
        "",
        f"主要工作流：{brief.primary_workflow or '待定'}",
        "",
        f"默认行动边界：{brief.autonomy_boundary or '待定'}",
        "",
        f"人工确认边界：{brief.human_review_boundary or '待定'}",
        "",
        f"资源边界：{brief.resource_boundary or '待定'}",
    ]
    if brief.expected_outputs:
        lines.extend(["", "预期输出：", *[f"- {item}" for item in brief.expected_outputs]])
    if brief.success_criteria:
        lines.extend(["", "第一版成功标准：", *[f"- {item}" for item in brief.success_criteria]])
    if brief.manufacturing_assumptions:
        lines.extend(["", "制造假设：", *[f"- {item}" for item in brief.manufacturing_assumptions]])
    if brief.blocking_questions:
        lines.extend(["", "我需要确认一个阻塞点：", brief.blocking_questions[0]])
    else:
        lines.extend(["", "当前没有阻塞问题。我会继续进入 Runtime Design，把它映射成 Kernel 可编译的运行结构。"])
    if brief.business_plan_text:
        lines.extend(["", "制造计划：", brief.business_plan_text])
    return "\n".join(lines).strip()


def _log_message(brief: ProductBriefOutput) -> str:
    question_count = len(brief.blocking_questions)
    if question_count:
        return f"Product Brief completed with {question_count} blocking question."
    return "Product Brief completed without blocking questions."


def _runtime_design_failed_patch(
    *,
    namespace_state: dict[str, Any],
    message: str,
    report: RuntimeDesignValidationReport | None = None,
) -> dict[str, Any]:
    next_state = {
        **namespace_state,
        "current_node": RUNTIME_DESIGN_NODE_ID,
        "status": "failed",
        "runtime_design_validation": report.model_dump(mode="json") if report is not None else {},
        "errors": [
            *list(namespace_state.get("errors") or []),
            {"where": RUNTIME_DESIGN_NODE_ID, "message": message},
        ],
    }
    return {
        "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
        "execution": {
            "current_node": RUNTIME_DESIGN_NODE_ID,
            "finished": True,
            "finish_status": "failed",
            "route_decision": "execution.finished",
            "last_error": message,
            "last_error_location": RUNTIME_DESIGN_NODE_ID,
        },
    }


def _runtime_design_log_message(
    design: RuntimeDesignOutput,
    report: RuntimeDesignValidationReport,
) -> str:
    return f"Runtime Design selected preset pattern {design.selected_pattern_id} and passed Kernel prevalidation."


def _capability_contract_failed_patch(
    *,
    namespace_state: dict[str, Any],
    message: str,
    report: CapabilityContractValidationReport | None = None,
) -> dict[str, Any]:
    next_state = {
        **namespace_state,
        "current_node": CAPABILITY_CONTRACT_NODE_ID,
        "status": "failed",
        "capability_contract_validation": report.model_dump(mode="json") if report is not None else {},
        "errors": [
            *list(namespace_state.get("errors") or []),
            {"where": CAPABILITY_CONTRACT_NODE_ID, "message": message},
        ],
    }
    return {
        "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
        "execution": {
            "current_node": CAPABILITY_CONTRACT_NODE_ID,
            "finished": True,
            "finish_status": "failed",
            "route_decision": "execution.finished",
            "last_error": message,
            "last_error_location": CAPABILITY_CONTRACT_NODE_ID,
        },
    }


def _capability_contract_log_message(report: CapabilityContractValidationReport) -> str:
    return (
        "Capability Contract passed registry validation with "
        f"{len(report.enabled_contracts)} enabled contract(s)."
    )


def _tool_manufacturing_failed_patch(
    *,
    namespace_state: dict[str, Any],
    message: str,
    report: ToolManufacturingReport | None = None,
) -> dict[str, Any]:
    next_state = {
        **namespace_state,
        "current_node": TOOL_MANUFACTURING_NODE_ID,
        "status": "failed",
        "tool_manufacturing_report": report.model_dump(mode="json") if report is not None else {},
        "errors": [
            *list(namespace_state.get("errors") or []),
            {"where": TOOL_MANUFACTURING_NODE_ID, "message": message},
        ],
    }
    return {
        "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
        "execution": {
            "current_node": TOOL_MANUFACTURING_NODE_ID,
            "finished": True,
            "finish_status": "failed",
            "route_decision": "execution.finished",
            "last_error": message,
            "last_error_location": TOOL_MANUFACTURING_NODE_ID,
        },
    }


def _package_build_failed_patch(
    *,
    namespace_state: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    next_state = {
        **namespace_state,
        "current_node": PACKAGE_BUILD_NODE_ID,
        "status": "failed",
        "errors": [
            *list(namespace_state.get("errors") or []),
            {"where": PACKAGE_BUILD_NODE_ID, "message": message},
        ],
    }
    return {
        "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
        "execution": {
            "current_node": PACKAGE_BUILD_NODE_ID,
            "finished": True,
            "finish_status": "failed",
            "route_decision": "execution.finished",
            "last_error": message,
            "last_error_location": PACKAGE_BUILD_NODE_ID,
        },
    }
