from __future__ import annotations

from dataclasses import dataclass
import json
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
    SCHEDULER_PREPARATION_NODE_ID,
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
from agent_factory.factory_package.scheduler_preparation import (
    prepare_scheduler_seeds,
    scheduler_preparation_message,
)
from agent_factory.factory_package.schemas import (
    CapabilityContractOutput,
    CapabilityContractValidationReport,
    PackageBuildModelPlan,
    ProductBriefOutput,
    RuntimeDesignOutput,
    RuntimeDesignValidationReport,
    SchedulerPreparationOutput,
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
    "scheduler_preparation",
    "scheduler_preparation_report",
    "package_build_plan",
    "package_build_report",
    "factory_response",
    "errors",
}
RUNTIME_DESIGN_VALIDATION_ATTEMPTS = 3
CAPABILITY_CONTRACT_VALIDATION_ATTEMPTS = 3


def factory_manufacturing_node_provider() -> StaticNodeProvider:
    return StaticNodeProvider(
        provider_id=FACTORY_NODE_PROVIDER_ID,
        nodes=(
            FactoryProductBriefNode(),
            FactoryRuntimeDesignNode(),
            FactoryCapabilityContractNode(),
            FactorySchedulerPreparationNode(),
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
class FactorySchedulerPreparationNode:
    node_type = "cognitive"
    supports_interrupt = True
    supports_subgraph_slot = False
    writable_sections = {"package_state", "conversation", "execution", "observability"}

    @property
    def impl_id(self) -> str:
        return f"builtin.factory.{SCHEDULER_PREPARATION_NODE_ID}"

    def execute(self, state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
        namespace_state = _initial_state(state)
        context.emit_event({"event_type": "scheduler_preparation_started"})
        product_brief_payload = dict(namespace_state.get("product_brief") or {})
        runtime_design_payload = dict(namespace_state.get("runtime_design") or {})
        capability_contract_payload = dict(namespace_state.get("capability_contract") or {})
        if not product_brief_payload or not runtime_design_payload or not capability_contract_payload:
            return _scheduler_preparation_failed_patch(
                namespace_state=namespace_state,
                message="Scheduler Preparation requires product_brief, runtime_design, and capability_contract.",
            )
        try:
            product_brief = ProductBriefOutput.model_validate(product_brief_payload)
            runtime_design = RuntimeDesignOutput.model_validate(runtime_design_payload)
            capability_contract = CapabilityContractOutput.model_validate(capability_contract_payload)
            output = prepare_scheduler_seeds(
                product_brief=product_brief,
                runtime_design=runtime_design,
                capability_contract=capability_contract,
            )
        except FactoryModelCallError as exc:
            return _scheduler_preparation_failed_patch(namespace_state=namespace_state, message=str(exc))
        except Exception as exc:
            return _scheduler_preparation_failed_patch(
                namespace_state=namespace_state,
                message=f"{type(exc).__name__}: {exc}",
            )
        if output.validation_report.status != "valid":
            return _scheduler_preparation_failed_patch(
                namespace_state={
                    **namespace_state,
                    "scheduler_preparation": output.model_dump(mode="json"),
                    "scheduler_preparation_report": output.validation_report.model_dump(mode="json"),
                },
                message="; ".join(output.validation_report.errors) or "Scheduler Preparation validation failed.",
            )

        for seed in output.approved_seeds:
            context.emit_event(
                {
                    "event_type": "scheduler_seed_confirmed",
                    "seed_id": seed.seed_id,
                    "title": seed.title,
                    "schedule_type": seed.schedule_type,
                    "schedule_expr": seed.schedule_expr,
                    "timezone": seed.timezone,
                }
            )
        context.emit_event(
            {
                "event_type": "scheduler_preparation_completed",
                "seed_count": len(output.approved_seeds),
            }
        )
        final_answer = scheduler_preparation_message(output)
        next_state = {
            **namespace_state,
            "current_node": SCHEDULER_PREPARATION_NODE_ID,
            "status": "scheduler_preparation_ready",
            "scheduler_preparation": output.model_dump(mode="json"),
            "scheduler_preparation_report": output.validation_report.model_dump(mode="json"),
            "factory_response": {"message": final_answer},
            "manufacturing_log": [
                *list(namespace_state.get("manufacturing_log") or []),
                {
                    "node_id": SCHEDULER_PREPARATION_NODE_ID,
                    "status": "completed",
                    "message": f"Prepared {len(output.approved_seeds)} scheduler seed(s).",
                },
            ],
        }
        return {
            "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
            "conversation": {"final_answer": final_answer},
            "execution": {
                "current_node": SCHEDULER_PREPARATION_NODE_ID,
                "finished": False,
                "finish_status": "running",
                "route_decision": "factory.next",
            },
        }


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
        scheduler_preparation_payload = dict(namespace_state.get("scheduler_preparation") or {})
        scheduler_preparation_report = dict(namespace_state.get("scheduler_preparation_report") or {})
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
        if not scheduler_preparation_payload:
            return _package_build_failed_patch(
                namespace_state=namespace_state,
                message="Package Build requires scheduler_preparation.v0 before it can run.",
            )
        if scheduler_preparation_report.get("status") != "valid":
            return _package_build_failed_patch(
                namespace_state=namespace_state,
                message="Package Build requires valid Scheduler Preparation output.",
            )
        try:
            product_brief = ProductBriefOutput.model_validate(product_brief_payload)
            runtime_design = RuntimeDesignOutput.model_validate(runtime_design_payload)
            capability_contract = CapabilityContractOutput.model_validate(capability_contract_payload)
            scheduler_preparation = SchedulerPreparationOutput.model_validate(scheduler_preparation_payload)
        except Exception as exc:
            return _package_build_failed_patch(
                namespace_state=namespace_state,
                message=f"Package Build inputs are invalid: {exc}",
            )

        approved_tools = []
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
                    "scheduler_preparation": json.dumps(scheduler_preparation_payload, ensure_ascii=False, indent=2),
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
            scheduler_preparation=scheduler_preparation,
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


def _scheduler_preparation_failed_patch(
    *,
    namespace_state: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    next_state = {
        **namespace_state,
        "current_node": SCHEDULER_PREPARATION_NODE_ID,
        "status": "failed",
        "errors": [
            *list(namespace_state.get("errors") or []),
            {"where": SCHEDULER_PREPARATION_NODE_ID, "message": message},
        ],
    }
    return {
        "package_state": {FACTORY_MANUFACTURING_NAMESPACE: next_state},
        "execution": {
            "current_node": SCHEDULER_PREPARATION_NODE_ID,
            "finished": True,
            "finish_status": "failed",
            "route_decision": "execution.finished",
            "last_error": message,
            "last_error_location": SCHEDULER_PREPARATION_NODE_ID,
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
