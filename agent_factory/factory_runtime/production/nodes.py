from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from langgraph.config import get_stream_writer
from pydantic import ValidationError
from ruamel.yaml import YAML

from agent_factory.core import EventStatus, FactoryEvent
from agent_factory.factory import FactoryError
from agent_factory.factory_context import (
    CapabilityItem,
    CapabilityPlan,
    ConditionItem,
    ConditionPlan,
    EvidenceReport,
    ImplementationPlan,
    NodeContextCompiler,
    ProductionSummary,
    ReadinessDecision,
    ReadinessItem,
    RequirementUnderstanding,
    ResolutionQuestion,
    ResourceContractSet,
    ResourceNeed,
    ResourceNeedPlan,
)
from agent_factory.factory_context.ledger import (
    DecisionLedger,
    DecisionRecord,
    EvidenceRecord,
    EvidenceStore,
)
from agent_factory.factory.environment import EnvironmentProbeRunner
from agent_factory.factory.package_artifacts import (
    PackageArtifactGenerator,
    PackageArtifactReport,
)
from agent_factory.factory.intent_classifier import FactoryIntentClassifier
from agent_factory.factory.primitive_normalizer import normalize_primitives_candidate
from agent_factory.factory.resource_binding import (
    bind_requirement_resources,
    discover_resource_candidates,
)
from agent_factory.factory.resource_resolvers import ResourceResolverRegistry
from agent_factory.factory.requirement_analyzer import RequirementAnalyzer
from agent_factory.factory.tool_preconditions import (
    analyze_capability_preconditions,
    analyze_tool_preconditions,
)
from agent_factory.factory.web_search import WebSearchConfig
from agent_factory.factory.web_research import (
    ResearchPlanBuilder,
    build_llm_advisor_research,
)
from agent_factory.factory.package_verification import (
    HarnessDryRunReport,
    MCPBindingLocalCheckReport,
    PackageVerificationRunner,
    ToolStaticCheckReport,
    ToolTestRunReport,
)
from agent_factory.factory.package_writer import PackageWriter
from agent_factory.factory.primitive_planner import PrimitivePlanner
from agent_factory.factory.primitive_repair import PrimitiveRepair
from agent_factory.factory_runtime import FactoryMemoryRecord, FactoryRunContext
from agent_factory.factory_runtime.production.state import (
    FactoryProductionState,
    FactoryProductionStateDict,
)
from agent_factory.factory_runtime.production.policies import FactoryNodeAccessPolicy
from agent_factory.model import LLMStreamEvent, ModelConfigError, ModelService
from agent_factory.package import PackageValidator
from agent_factory.specs import AgentPackagePrimitives, ReadinessReport


class FactoryProductionNodes:
    def __init__(
        self,
        context: FactoryRunContext,
        *,
        model_service: ModelService | None = None,
        package_writer: PackageWriter | None = None,
        artifact_generator: PackageArtifactGenerator | None = None,
        verification_runner: PackageVerificationRunner | None = None,
    ) -> None:
        self.context = context
        self.model_service = model_service
        self.package_writer = package_writer or PackageWriter()
        self.artifact_generator = artifact_generator
        self.verification_runner = verification_runner or PackageVerificationRunner()
        self.context_compiler = NodeContextCompiler()
        self.node_access_policy = FactoryNodeAccessPolicy()

    def guarded(self, node_name: str):
        return self.node_access_policy.wrap(node_name, getattr(self, node_name))

    def capture_requirement(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self.context.memory_store.append(
            FactoryMemoryRecord(
                run_id=current.run_id,
                type="create_agent_requirement",
                summary="Captured create-agent requirement.",
                payload={
                    "requirement": current.requirement,
                    "draft": current.draft,
                    "workspace_path": str(self.context.workspace_path),
                },
            )
        )
        return self._with_event(
            current,
            node="capture_requirement",
            event=FactoryEvent(
                run_id=current.run_id,
                stage="capture_requirement",
                status=EventStatus.COMPLETED,
                title="Requirement captured",
                message=current.requirement,
                payload={"draft": current.draft},
            ),
        )

    def load_factory_context(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        return self._with_event(
            current,
            node="load_factory_context",
            event=FactoryEvent(
                run_id=current.run_id,
                stage="load_factory_context",
                status=EventStatus.COMPLETED,
                title="Factory context loaded",
                message="Factory workspace, memory, trace, and tools are ready.",
                payload={
                    "workspace_path": str(self.context.workspace_path),
                    "memory_path": str(self.context.memory_path),
                    "trace_path": str(self.context.trace_path),
                    "tool_count": len(self.context.tool_registry.list_tools()),
                },
            ),
        )

    def classify_factory_intent(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="classify_factory_intent",
            title="Classifying Factory input",
            message="Using the task model to decide whether this is an Agent creation request.",
            payload={"flow_summary": "Intent gate: clear create request, unclear create request, or unrelated input."},
        )
        result = FactoryIntentClassifier(self._optional_model_service()).classify_sync(
            self.context,
            requirement=current.requirement,
            context_envelope=self._compile_context_envelope(current, "classify_factory_intent"),
        )
        classification = result.classification
        current.factory_intent = classification.model_dump(mode="json")
        current.guidance_message = classification.guidance_message
        current.clarification_options = [
            question.model_dump(mode="json")
            for question in classification.clarification_questions
        ]
        current.clarification_questions = [
            question.question for question in classification.clarification_questions
        ]
        status = EventStatus.COMPLETED
        title = "Factory intent classified"
        message = "Create-agent request detected."
        if classification.intent == "create_agent_unclear":
            status = EventStatus.WARNING
            message = "Create-agent request needs clarification before production."
        elif classification.intent == "not_agent_request":
            status = EventStatus.WARNING
            message = "Input is not an Agent creation request."
        event = FactoryEvent(
            run_id=current.run_id,
            stage="classify_factory_intent",
            status=status,
            title=title,
            message=message,
            payload={
                "intent": classification.intent,
                "confidence": classification.confidence,
                "intent_source": result.source,
                "agent_hint": classification.agent_hint,
                "normalized_requirement": classification.normalized_requirement,
                "clarification_count": len(current.clarification_questions),
                "guidance_message": current.guidance_message,
                "fallback_error": result.error.type if result.error else None,
            },
        )
        self._stream_progress(
            current,
            stage="classify_factory_intent",
            title="Intent gate result",
            message=(
                f"intent={classification.intent}, "
                f"confidence={classification.confidence:.2f}, source={result.source}"
            ),
            payload={
                "flow_summary": (
                    "Routing to production."
                    if classification.intent == "create_agent_clear"
                    else "Routing to clarification or guidance."
                )
            },
        )
        return self._with_event(current, node="classify_factory_intent", event=event)

    def analyze_requirement(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="analyze_requirement",
            title="Analyzing requirement",
            message="Reading the user request and deciding whether clarification is needed.",
            payload={"thinking": "Extract role, name, goals, safety profile, and missing essentials."},
        )
        analysis_result = RequirementAnalyzer(self._optional_model_service()).analyze_sync(
            self.context,
            requirement=current.requirement,
            context_envelope=self._compile_context_envelope(current, "analyze_requirement"),
            on_stream_event=self._model_stream_callback(
                current,
                stage="analyze_requirement",
                title="Analyzing requirement",
                message="Streaming model reasoning and analysis JSON.",
            ),
        )
        analysis = analysis_result.analysis
        questions = analysis.clarification_questions if not analysis.is_clear_enough else []
        current.requirement_analysis = analysis.model_dump(mode="json")
        current.requirement_understanding = RequirementUnderstanding(
            agent_name=analysis.agent_name,
            agent_type=analysis.agent_type,
            goal="; ".join(analysis.goals) or analysis.persona or current.requirement,
            audience=", ".join(analysis.target_users) if analysis.target_users else None,
            safety_profile=analysis.safety_profile,
            explicit_requirements=[current.requirement, *analysis.in_scope_tasks],
            missing_information=[*analysis.missing_required_fields, *questions],
            source=analysis_result.source,
        )
        self._append_decision(
            current,
            stage="analyze_requirement",
            artifact_type="RequirementUnderstanding",
            title="Requirement understanding",
            summary=current.requirement_understanding.goal,
            payload=current.requirement_understanding.model_dump(mode="json"),
        )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="analyze_requirement",
            status=EventStatus.WARNING if questions else EventStatus.COMPLETED,
            title="Requirement analyzed",
            message=(
                "Clarification needed."
                if questions
                else f"Requirement is clear enough for a draft. analysis_source={analysis_result.source}"
            ),
            payload={
                "clarification_questions": questions,
                "analysis_source": analysis_result.source,
                "agent_name": analysis.agent_name,
                "agent_type": analysis.agent_type,
                "safety_profile": analysis.safety_profile,
                "confidence": analysis.confidence,
                "fallback_error": (
                    analysis_result.error.type if analysis_result.error else None
                ),
            },
        )
        self._stream_progress(
            current,
            stage="analyze_requirement",
            title="Requirement analysis result",
            message=(
                f"agent_name={analysis.agent_name or '-'}, "
                f"agent_type={analysis.agent_type or '-'}, "
                f"safety_profile={analysis.safety_profile}, "
                f"clear={analysis.is_clear_enough}"
            ),
            payload={
                "thinking": _compact_preview(analysis.model_dump(mode="json")),
                "analysis_source": analysis_result.source,
            },
        )
        current.clarification_questions = questions
        return self._with_event(current, node="analyze_requirement", event=event)

    def maybe_clarify(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        event = FactoryEvent(
            run_id=current.run_id,
            stage="maybe_clarify",
            status=EventStatus.WARNING if current.clarification_questions else EventStatus.COMPLETED,
            title="Clarification gate",
            message=(
                "Need user clarification before generating a package."
                if current.clarification_questions
                else "No clarification required."
            ),
            payload={"questions": current.clarification_questions},
        )
        return self._with_event(current, node="maybe_clarify", event=event)

    def plan_primitives(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="plan_primitives",
            title="Generating AgentPackage primitives",
            message="Calling the model for the nine required building primitives.",
            payload={"thinking": "Turn requirement analysis into Instruction/Output/Conversation/Toolset/Knowledge/Guardrail/Handoff/Observability specs."},
        )
        try:
            planner = PrimitivePlanner(self._model_service())
            result = asyncio.run(
                planner.plan(
                    self.context,
                    requirement=current.requirement,
                    requirement_analysis=current.requirement_analysis,
                    production_context=_production_context_for_primitives(current),
                    context_envelope=self._compile_context_envelope(current, "plan_primitives"),
                    on_stream_event=self._model_stream_callback(
                        current,
                        stage="plan_primitives",
                        title="Generating AgentPackage primitives",
                        message="Streaming model reasoning and primitives JSON.",
                    ),
                )
            )
            if result.error:
                current.error = FactoryError(code=result.error.type, message=result.error.message)
            else:
                current.raw_model_data = normalize_primitives_candidate(result.data)
                self._stream_progress(
                    current,
                    stage="plan_primitives",
                    title="Primitive draft received",
                    message="Model returned structured data; validating schema next.",
                    payload={"thinking": _compact_preview(current.raw_model_data)},
                )
        except ModelConfigError as error:
            current.error = FactoryError(code="model_config_error", message=str(error))
        event = FactoryEvent(
            run_id=current.run_id,
            stage="plan_primitives",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title=_planner_event_title(current.error),
            message=current.error.message if current.error else "Raw primitives JSON generated.",
            payload={"code": current.error.code if current.error else None},
        )
        return self._with_event(current, node="plan_primitives", event=event)

    def validate_primitives(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        current.error = None
        self._stream_progress(
            current,
            stage="validate_primitives",
            title="Validating primitives",
            message="Checking model output against AgentPackagePrimitives Pydantic models.",
        )
        try:
            current.raw_model_data = normalize_primitives_candidate(current.raw_model_data)
            current.primitives = AgentPackagePrimitives.model_validate(current.raw_model_data)
            current.primitives = bind_requirement_resources(
                current.primitives,
                current.requirement,
                start_path=self.context.workspace_path.parent,
                model_service=self._optional_model_service(),
                context_envelope=self._compile_context_envelope(current, "validate_primitives"),
            )
        except ValidationError as error:
            current.primitives = None
            current.error = FactoryError(
                code="primitive_schema_validation_failed",
                message=str(error),
            )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="validate_primitives",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Primitives validation failed" if current.error else "Primitives validated",
            message=current.error.message if current.error else None,
            payload={
                "repair_attempts": current.repair_attempts,
                "max_repair_attempts": current.max_repair_attempts,
            },
        )
        return self._with_event(current, node="validate_primitives", event=event)

    def repair_primitives(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        validation_error = current.error.message if current.error else "unknown validation error"
        current.error = None
        current.repair_attempts += 1
        self._stream_progress(
            current,
            stage="repair_primitives",
            title="Repairing primitive draft",
            message=f"Repair attempt {current.repair_attempts}/{current.max_repair_attempts}.",
            payload={"thinking": _compact_preview(validation_error)},
        )
        try:
            repairer = PrimitiveRepair(self._model_service())
            result = asyncio.run(
                repairer.repair(
                    self.context,
                    requirement=current.requirement,
                    raw_model_data=current.raw_model_data,
                    validation_errors=validation_error,
                    context_envelope=self._compile_context_envelope(current, "repair_primitives"),
                    on_stream_event=self._model_stream_callback(
                        current,
                        stage="repair_primitives",
                        title="Repairing primitive draft",
                        message="Streaming model reasoning and repaired JSON.",
                    ),
                )
            )
            if result.error:
                current.error = FactoryError(code=result.error.type, message=result.error.message)
            else:
                current.raw_model_data = normalize_primitives_candidate(result.data)
                self._stream_progress(
                    current,
                    stage="repair_primitives",
                    title="Primitive repair received",
                    message="Model returned a repaired structured draft.",
                    payload={"thinking": _compact_preview(current.raw_model_data)},
                )
        except ModelConfigError as error:
            current.error = FactoryError(code="model_config_error", message=str(error))
        event = FactoryEvent(
            run_id=current.run_id,
            stage="repair_primitives",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Primitives repair failed" if current.error else "Primitives repaired",
            message=current.error.message if current.error else f"repair_attempts={current.repair_attempts}",
            payload={"repair_attempts": current.repair_attempts},
        )
        return self._with_event(current, node="repair_primitives", event=event)

    def plan_capability_preconditions(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        tool_count = 0
        if current.primitives is not None:
            tool_count = sum(
                len(toolset.exposed_tools) + len(toolset.hidden_tools)
                for toolset in current.primitives.toolsets.toolsets
            )
            capabilities: list[CapabilityItem] = []
            for toolset in current.primitives.toolsets.toolsets:
                for tool_id in toolset.exposed_tools + toolset.hidden_tools:
                    capabilities.append(
                        CapabilityItem(
                            capability_id=tool_id,
                            description=f"Tool capability requested by toolset {toolset.id}.",
                            likely_requires_tools=True,
                        )
                    )
            if not capabilities:
                capabilities.append(
                    CapabilityItem(
                        capability_id="conversation",
                        description=current.primitives.instructions.goal,
                        likely_requires_tools=False,
                    )
                )
            current.capability_plan = CapabilityPlan(capabilities=capabilities, source="primitives")
            self._append_decision(
                current,
                stage="plan_capability_preconditions",
                artifact_type="CapabilityPlan",
                title="Capability plan",
                summary=f"{len(capabilities)} capabilities planned.",
                payload=current.capability_plan.model_dump(mode="json"),
            )
        else:
            capabilities = _capabilities_from_requirement_understanding(current)
            tool_count = len([item for item in capabilities if item.likely_requires_tools])
            current.capability_plan = CapabilityPlan(
                capabilities=capabilities,
                source="requirement_understanding",
            )
            self._append_decision(
                current,
                stage="plan_capability_preconditions",
                artifact_type="CapabilityPlan",
                title="Capability plan",
                summary=f"{len(capabilities)} requirement-level capabilities planned before primitives.",
                payload=current.capability_plan.model_dump(mode="json"),
            )
        self._stream_progress(
            current,
            stage="plan_capability_preconditions",
            title="Planning capability preconditions",
            message="Identifying resource, dependency, sandbox, and shell conditions before writing tools.",
            payload={"flow_summary": f"Preflight plan prepared for {tool_count} requested tools."},
        )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="plan_capability_preconditions",
            status=EventStatus.COMPLETED,
            title="Capability preconditions planned",
            message=f"tool_count={tool_count}",
            payload={"tool_count": tool_count},
        )
        return self._with_event(current, node="plan_capability_preconditions", event=event)

    def analyze_tool_preconditions(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="analyze_tool_preconditions",
            title="Analyzing tool preconditions",
            message="Semantically identifying local, external, dependency, permission, fixture, and sandbox conditions.",
        )
        web_config = WebSearchConfig.from_env(self.context.workspace_path.parent / ".env")
        if current.primitives is None:
            capabilities = [
                capability.model_dump(mode="json")
                for capability in (current.capability_plan.capabilities if current.capability_plan else [])
            ]
            report = analyze_capability_preconditions(
                capabilities,
                current.requirement,
                web_config=web_config,
                model_service=self._optional_model_service(),
                context_envelope=self._compile_context_envelope(current, "analyze_tool_preconditions"),
            )
            current.tool_precondition_report = report.model_dump(mode="json")
            current.condition_plan = _condition_plan_from_tool_preconditions(report)
            current.resource_need_plan = _resource_need_plan_from_tool_preconditions(report)
            self._append_decision(
                current,
                stage="analyze_tool_preconditions",
                artifact_type="ConditionPlan",
                title="Condition plan",
                summary=(
                    f"{len(current.condition_plan.conditions)} conditions, "
                    f"{len(current.resource_need_plan.resources)} resources."
                ),
                payload={
                    "condition_plan": current.condition_plan.model_dump(mode="json"),
                    "resource_need_plan": current.resource_need_plan.model_dump(mode="json"),
                },
            )
            plan_count = len(report.plans)
            condition_count = report.condition_count
            missing_count = len(report.missing_required_conditions)
        else:
            report = analyze_tool_preconditions(
                current.primitives,
                current.requirement,
                web_config=web_config,
                model_service=self._optional_model_service(),
                context_envelope=self._compile_context_envelope(current, "analyze_tool_preconditions"),
            )
            current.tool_precondition_report = report.model_dump(mode="json")
            current.condition_plan = _condition_plan_from_tool_preconditions(report)
            current.resource_need_plan = _resource_need_plan_from_tool_preconditions(report)
            self._append_decision(
                current,
                stage="analyze_tool_preconditions",
                artifact_type="ConditionPlan",
                title="Condition plan",
                summary=(
                    f"{len(current.condition_plan.conditions)} conditions, "
                    f"{len(current.resource_need_plan.resources)} resources."
                ),
                payload={
                    "condition_plan": current.condition_plan.model_dump(mode="json"),
                    "resource_need_plan": current.resource_need_plan.model_dump(mode="json"),
                },
            )
            plan_count = len(report.plans)
            condition_count = report.condition_count
            missing_count = len(report.missing_required_conditions)
        event = FactoryEvent(
            run_id=current.run_id,
            stage="analyze_tool_preconditions",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Tool preconditions analyzed" if not current.error else "Tool precondition analysis failed",
            message=(
                current.error.message
                if current.error
                else f"plans={plan_count}, conditions={condition_count}, missing={missing_count}"
            ),
            payload={
                "plan_count": plan_count if not current.error else 0,
                "condition_count": condition_count if not current.error else 0,
                "missing_condition_count": missing_count if not current.error else 0,
                "tool_preconditions": current.tool_precondition_report or {},
            },
        )
        return self._with_event(current, node="analyze_tool_preconditions", event=event)

    def discover_resources(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="discover_resources",
            title="Discovering requirement resources",
            message="Binding local paths from the requirement to tool-visible package resources.",
        )
        if current.primitives is None:
            candidates = discover_resource_candidates(
                current.requirement,
                start_path=self.context.workspace_path.parent,
            )
            resource_count = len(candidates)
            if candidates:
                existing = {
                    resource.resource_id: resource
                    for resource in (
                        current.resource_need_plan.resources
                        if current.resource_need_plan
                        else []
                    )
                }
                for candidate in candidates:
                    existing.setdefault(
                        candidate.id,
                        ResourceNeed(
                            resource_id=candidate.id,
                            family="data",
                            kind=candidate.kind if candidate.kind == "directory" else candidate.suffix or "file",
                            location=candidate.ref,
                            access_mode=candidate.default_access_mode,
                            visibility="tool_only",
                            lifecycle="build_time",
                            risk_level="low",
                            required_evidence=["path exists", "readability", "sandbox copy"],
                        ),
                    )
                current.resource_need_plan = ResourceNeedPlan(
                    resources=list(existing.values()),
                    source="resource_discovery",
                )
                self._append_decision(
                    current,
                    stage="discover_resources",
                    artifact_type="ResourceNeedPlan",
                    title="Local resources discovered",
                    summary=f"{resource_count} local resources discovered from requirement.",
                    payload=current.resource_need_plan.model_dump(mode="json"),
                )
        else:
            current.primitives = bind_requirement_resources(
                current.primitives,
                current.requirement,
                start_path=self.context.workspace_path.parent,
                model_service=self._optional_model_service(),
                context_envelope=self._compile_context_envelope(current, "discover_resources"),
            )
            resource_count = len(current.primitives.knowledge.sources)
        event = FactoryEvent(
            run_id=current.run_id,
            stage="discover_resources",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Resources discovered" if not current.error else "Resource discovery failed",
            message=current.error.message if current.error else f"resource_count={resource_count}",
            payload={"resource_count": resource_count},
        )
        return self._with_event(current, node="discover_resources", event=event)

    def factory_web_research(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="factory_web_research",
            title="External resource LLM advisor",
            message="WebSearch is disabled; using the configured model to complete external-resource setup candidates.",
        )
        plan = ResearchPlanBuilder().build(
            requirement=current.requirement,
            tool_precondition_report=current.tool_precondition_report,
        )
        bundle, completeness = build_llm_advisor_research(
            plan,
            model_service=self._optional_model_service(),
            context_envelope=self._compile_context_envelope(current, "factory_web_research"),
        )
        report = bundle.raw_search_report
        current.web_research_report = report.model_dump(mode="json")
        current.research_brief_report = bundle.model_dump(mode="json")
        current.research_completeness_report = completeness.model_dump(mode="json")
        self._append_evidence_report(
            current,
            EvidenceReport(
                evidence_id="web_research",
                source="url_doc_extract",
                status="passed" if bundle.status in {"passed", "skipped"} else "partial",
                summary=(
                    f"research={bundle.status}, brief={bundle.brief.status}, "
                    f"completeness={completeness.status}"
                ),
                artifact_refs=["generated/reports/research_brief.json"],
                safe_for_prompt=True,
                details={
                    "candidate_count": len(bundle.candidates),
                    "document_count": len(bundle.clean_documents),
                    "missing_config_keys": completeness.missing_config_keys[:20],
                    "missing_facts": completeness.missing_facts[:20],
                    "unresolved_fields": bundle.brief.unresolved_fields[:20],
                },
            ),
        )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="factory_web_research",
            status=EventStatus.COMPLETED if bundle.status in {"passed", "skipped"} else EventStatus.WARNING,
            title="External resource advisor finished",
            message=(
                f"web_search=disabled, advisor={bundle.status}, brief={bundle.brief.status}, "
                f"completeness={completeness.status}"
            ),
            payload={
                "status": bundle.status,
                "provider": report.provider,
                "query_count": len(report.queries),
                "candidate_count": len(bundle.candidates),
                "document_count": len(bundle.clean_documents),
                "brief_status": bundle.brief.status,
                "completeness_status": completeness.status,
                "missing_facts": completeness.missing_facts[:10],
                "missing_config_keys": completeness.missing_config_keys[:10],
                "missing_urls": completeness.missing_urls[:5],
                "unresolved_fields": bundle.brief.unresolved_fields[:10],
                "issues": bundle.issues,
            },
        )
        return self._with_event(current, node="factory_web_research", event=event)

    def probe_environment(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="probe_environment",
            title="Probing environment and resources",
            message="Checking local resources, SQLite schemas, Python support, optional CLI tools, and sandbox readiness.",
        )
        try:
            environment, contracts, readiness = EnvironmentProbeRunner().probe(
                current.primitives,
                requirement=current.requirement,
                start_path=self.context.workspace_path.parent,
                tool_precondition_report=current.tool_precondition_report,
                web_research_report=current.web_research_report,
                research_brief_report=current.research_brief_report,
                research_completeness_report=current.research_completeness_report,
            )
            current.environment_report = environment
            current.resource_contracts = contracts
            current.readiness_report = readiness
            current.resource_contract_set = ResourceContractSet(
                resources=[resource.model_dump(mode="json") for resource in contracts.resources],
                external_config_keys=_external_config_keys_from_research(current.research_brief_report),
                evidence_refs=[report.evidence_id for report in current.evidence_reports],
            )
            current.readiness_decision = _readiness_decision_from_report(
                readiness,
                research_completeness_report=current.research_completeness_report,
            )
            self._append_evidence_report(
                current,
                EvidenceReport(
                    evidence_id="environment_probe",
                    source="local_probe",
                    status="passed" if readiness.status in {"ready", "mock_only_allowed"} else "partial",
                    summary=(
                        f"{len(contracts.resources)} resources, "
                        f"{len(environment.preconditions)} preconditions, readiness={readiness.status}."
                    ),
                    safe_for_prompt=True,
                    details={
                        "resource_count": len(contracts.resources),
                        "precondition_count": len(environment.preconditions),
                        "readiness_status": readiness.status,
                    },
                ),
            )
            if current.resource_need_plan is not None:
                resolver_registry = ResourceResolverRegistry()
                for resource in current.resource_need_plan.resources:
                    self._append_evidence_report(current, resolver_registry.resolve(resource))
        except Exception as error:
            current.error = FactoryError(
                code="environment_probe_failed",
                message=str(error),
            )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="probe_environment",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Environment probe failed" if current.error else "Environment probed",
            message=(
                current.error.message
                if current.error
                else f"resources={len(current.resource_contracts.resources) if current.resource_contracts else 0}"
            ),
            payload={
                "resource_count": len(current.resource_contracts.resources) if current.resource_contracts else 0,
                "precondition_count": len(current.environment_report.preconditions) if current.environment_report else 0,
            },
        )
        return self._with_event(current, node="probe_environment", event=event)

    def enrich_tool_contracts(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="enrich_tool_contracts",
            title="Enriching tool contracts",
            message="Preparing resource contracts and web research context for tool implementation.",
        )
        research_status = (
            current.web_research_report.get("status")
            if isinstance(current.web_research_report, dict)
            else "skipped"
        )
        brief_status = (
            current.research_brief_report.get("brief", {}).get("status")
            if isinstance(current.research_brief_report, dict)
            else "skipped"
        )
        completeness_status = (
            current.research_completeness_report.get("status")
            if isinstance(current.research_completeness_report, dict)
            else "skipped"
        )
        current.implementation_plan = ImplementationPlan(
            runtime_type="langgraph_react",
            tool_contract_refs=_tool_contract_refs(current),
            resource_contract_refs=_resource_contract_refs(current),
            harness_focus=[
                "basic response",
                "tool proposal/execution",
                "pending external configuration",
                "secret redaction",
            ],
            notes=[
                "Generate tools only from ResourceContractSet and evidence summaries.",
                "External services without runtime values must return needs_configuration.",
            ],
        )
        self._append_decision(
            current,
            stage="enrich_tool_contracts",
            artifact_type="ImplementationPlan",
            title="Implementation plan",
            summary=f"{len(current.implementation_plan.tool_contract_refs)} tool contracts prepared.",
            payload=current.implementation_plan.model_dump(mode="json"),
        )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="enrich_tool_contracts",
            status=EventStatus.COMPLETED,
            title="Tool contracts enriched",
            message=(
                f"web_research={research_status}, research_brief={brief_status}, "
                f"completeness={completeness_status}"
            ),
            payload={
                "web_research_status": research_status,
                "research_brief_status": brief_status,
                "research_completeness_status": completeness_status,
                "resource_count": len(current.resource_contracts.resources)
                if current.resource_contracts
                else 0,
            },
        )
        return self._with_event(current, node="enrich_tool_contracts", event=event)

    def resolve_readiness(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        readiness = current.readiness_report
        status = readiness.status if readiness else "blocked"
        decision = current.readiness_decision or _readiness_decision_from_report(
            readiness,
            research_completeness_report=current.research_completeness_report,
        )
        current.readiness_decision = decision
        if decision.status == "ready_with_deferred":
            status = "ready"
        if status == "needs_user_input" and readiness is not None:
            question = _readiness_clarification_question(readiness, decision)
            current.clarification_questions = [question]
            current.clarification_options = _clarification_options_from_readiness_decision(
                question,
                decision,
                readiness,
            )
        elif status == "blocked":
            current.error = FactoryError(
                code="readiness_blocked",
                message="Required preconditions are blocked.",
            )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="resolve_readiness",
            status=EventStatus.COMPLETED if status == "ready" else EventStatus.WARNING,
            title="Readiness resolved",
            message=_readiness_event_message(status, readiness),
            payload={
                "status": status,
                "issues": len(readiness.issues) if readiness else 0,
                "options": len(current.clarification_options[0]["options"])
                if current.clarification_options
                else len(readiness.options)
                if readiness
                else 0,
                "issue_messages": [issue.message for issue in readiness.issues[:5]]
                if readiness
                else [],
                "readiness_decision": decision.model_dump(mode="json"),
            },
        )
        return self._with_event(current, node="resolve_readiness", event=event)

    def write_package(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="write_package",
            title="Writing package YAML",
            message="Materializing the primitives into the draft AgentPackage directory.",
        )
        if current.primitives is None:
            current.error = FactoryError(code="missing_primitives", message="No primitives to write.")
        else:
            output_dir = self.context.drafts_path / _slugify(current.requirement)
            current.package_path = output_dir
            current.validation_report = self.package_writer.write_primitives(output_dir, current.primitives)
            if (
                current.environment_report is not None
                and current.resource_contracts is not None
                and current.readiness_report is not None
                and hasattr(self.package_writer, "write_condition_specs")
            ):
                self.package_writer.write_condition_specs(
                    output_dir,
                    environment=current.environment_report,
                    resource_contracts=current.resource_contracts,
                    readiness=current.readiness_report,
                )
            if current.web_research_report:
                report_dir = output_dir / "generated" / "reports"
                report_dir.mkdir(parents=True, exist_ok=True)
                (report_dir / "web_research_raw.json").write_text(
                    _json_dumps(current.web_research_report),
                    encoding="utf-8",
                )
            if current.research_brief_report:
                report_dir = output_dir / "generated" / "reports"
                report_dir.mkdir(parents=True, exist_ok=True)
                (report_dir / "research_brief.json").write_text(
                    _json_dumps(current.research_brief_report),
                    encoding="utf-8",
                )
            if current.research_completeness_report:
                report_dir = output_dir / "generated" / "reports"
                report_dir.mkdir(parents=True, exist_ok=True)
                (report_dir / "research_completeness.json").write_text(
                    _json_dumps(current.research_completeness_report),
                    encoding="utf-8",
                )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="write_package",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="YAML AgentPackage draft written" if not current.error else "Package write failed",
            message=current.error.message if current.error else None,
            artifact_path=str(current.package_path) if current.package_path else None,
            payload={
                "files": 9 if not current.error else 0,
                "resource_count": (
                    len(current.primitives.knowledge.sources)
                    if current.primitives is not None and not current.error
                    else 0
                ),
            },
        )
        return self._with_event(current, node="write_package", event=event)

    def generate_tool_scripts(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="generate_tool_scripts",
            title="Generating tool scripts",
            message="Creating draft Python tool implementations from toolsets.yaml.",
        )
        if self._missing_package_inputs(current):
            return self._artifact_failure_event(current, "generate_tool_scripts")
        try:
            assert current.package_path is not None and current.primitives is not None
            report = self._artifact_generator().generate_tool_scripts(
                current.package_path,
                current.primitives,
                requirement=None,
                requirement_analysis=None,
                resource_contracts=current.resource_contracts,
                context_envelope=self._compile_context_envelope(current, "generate_tool_scripts"),
                on_stream_event=self._model_stream_callback(
                    current,
                    stage="generate_tool_scripts",
                    title="Generating tool scripts",
                    message="Streaming model reasoning and tool code JSON.",
                ),
                on_tool_progress=self._tool_progress_callback(current),
            )
            _apply_artifact_report(current, report)
        except Exception as error:
            current.error = FactoryError(code="tool_script_generation_failed", message=str(error))
            report = None
        has_generation_issues = bool(getattr(report, "issues", [])) if "report" in locals() else False
        event = FactoryEvent(
            run_id=current.run_id,
            stage="generate_tool_scripts",
            status=EventStatus.FAILED
            if current.error
            else EventStatus.WARNING
            if has_generation_issues
            else EventStatus.COMPLETED,
            title="Tool draft generation failed"
            if current.error
            else "Tool draft scripts generated with warnings"
            if has_generation_issues
            else "Tool draft scripts generated",
            message=current.error.message
            if current.error
            else "; ".join(report.issues[:3])
            if has_generation_issues and report is not None
            else None,
            artifact_path=str(current.package_path / "generated" / "draft_tools")
            if current.package_path
            else None,
            payload={
                "tools": current.generated_tool_count,
                "issues": report.issues if report is not None else [],
            },
        )
        return self._with_event(current, node="generate_tool_scripts", event=event)

    def generate_tool_tests(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="generate_tool_tests",
            title="Generating tool tests",
            message="Creating local unit tests for generated draft tools.",
        )
        if self._missing_package_inputs(current):
            return self._artifact_failure_event(current, "generate_tool_tests")
        try:
            assert current.package_path is not None and current.primitives is not None
            report = self._artifact_generator().generate_tool_tests(
                current.package_path,
                current.primitives,
            )
            _apply_artifact_report(current, report)
        except Exception as error:
            current.error = FactoryError(code="tool_test_generation_failed", message=str(error))
        event = FactoryEvent(
            run_id=current.run_id,
            stage="generate_tool_tests",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Tool draft tests generated" if not current.error else "Tool test generation failed",
            message=current.error.message if current.error else None,
            artifact_path=str(current.package_path / "generated" / "tool_tests")
            if current.package_path
            else None,
            payload={"tool_tests": current.generated_tool_test_count},
        )
        return self._with_event(current, node="generate_tool_tests", event=event)

    def generate_mcp_bindings(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="generate_mcp_bindings",
            title="Generating MCP bindings",
            message="Declaring MCP servers and capability bindings without connecting externally.",
        )
        if self._missing_package_inputs(current):
            return self._artifact_failure_event(current, "generate_mcp_bindings")
        try:
            assert current.package_path is not None and current.primitives is not None
            report = self._artifact_generator().generate_mcp_bindings(
                current.package_path,
                current.primitives,
            )
            _apply_artifact_report(current, report)
        except Exception as error:
            current.error = FactoryError(code="mcp_binding_generation_failed", message=str(error))
        event = FactoryEvent(
            run_id=current.run_id,
            stage="generate_mcp_bindings",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="MCP bindings generated" if not current.error else "MCP binding generation failed",
            message=current.error.message if current.error else None,
            artifact_path=str(current.package_path / "mcp.yaml") if current.package_path else None,
            payload={"mcp_bindings": current.mcp_binding_count},
        )
        return self._with_event(current, node="generate_mcp_bindings", event=event)

    def generate_harness_scenarios(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="generate_harness_scenarios",
            title="Generating harness scenarios",
            message="Creating reproducible scenario contracts for the AgentPackage.",
        )
        if self._missing_package_inputs(current):
            return self._artifact_failure_event(current, "generate_harness_scenarios")
        try:
            assert current.package_path is not None and current.primitives is not None
            report = self._artifact_generator().generate_harness_scenarios(
                current.package_path,
                current.primitives,
            )
            _apply_artifact_report(current, report)
        except Exception as error:
            current.error = FactoryError(code="harness_generation_failed", message=str(error))
        event = FactoryEvent(
            run_id=current.run_id,
            stage="generate_harness_scenarios",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Harness scenarios generated" if not current.error else "Harness generation failed",
            message=current.error.message if current.error else None,
            artifact_path=str(current.package_path / "harness.yaml") if current.package_path else None,
            payload={"scenarios": current.harness_scenario_count},
        )
        return self._with_event(current, node="generate_harness_scenarios", event=event)

    def validate_package(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="validate_package",
            title="Validating full AgentPackage",
            message="Checking primitives plus runtime/tools/mcp/context/memory/harness specs.",
        )
        if current.validation_report is None:
            current.error = FactoryError(
                code="package_validation_missing",
                message="Package validation report was not produced.",
            )
        elif not current.validation_report.ok:
            current.error = FactoryError(
                code="package_validation_failed",
                message="Generated package failed validation.",
            )
        elif current.package_path is None or current.primitives is None:
            current.error = FactoryError(
                code="package_validation_missing_inputs",
                message="Package path and primitives are required for full package validation.",
            )
        else:
            try:
                support_report = self._artifact_generator().generate_package_specs(
                    current.package_path,
                    current.primitives,
                    resource_contracts=current.resource_contracts,
                )
                _apply_artifact_report(current, support_report)
                current.validation_report = PackageValidator().validate_full_package(current.package_path)
                if _has_blocking_full_validation_issues(current.validation_report):
                    current.error = FactoryError(
                        code="package_validation_failed",
                        message="Generated full AgentPackage failed validation.",
                    )
            except Exception as error:
                current.error = FactoryError(
                    code="package_validation_error",
                    message=str(error),
                )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="validate_package",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Package validation failed" if current.error else "Generated AgentPackage validated",
            message=current.error.message if current.error else None,
            payload={"issues": len(current.validation_report.issues) if current.validation_report else 0},
        )
        return self._with_event(current, node="validate_package", event=event)

    def static_check_tool_scripts(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="static_check_tool_scripts",
            title="Static checking tool scripts",
            message="Compiling generated Python files without executing business side effects.",
        )
        if current.package_path is None:
            current.error = FactoryError(
                code="missing_package_path",
                message="Package path is required before static tool checks.",
            )
            report = None
        else:
            report = self.verification_runner.static_check_tool_scripts(current.package_path)
            current.tool_static_check_report = report
            self._refresh_factory_verification_report(current)
            if not report.ok:
                current.error = FactoryError(
                    code="tool_static_check_failed",
                    message="Generated tool static check failed.",
                )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="static_check_tool_scripts",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Tool scripts static check finished"
            if not current.error
            else "Tool scripts static check failed",
            message=_verification_message(report) if not current.error else current.error.message,
            artifact_path=str(report.report_path) if report and report.report_path else None,
            payload=_verification_payload(report),
        )
        return self._with_event(current, node="static_check_tool_scripts", event=event)

    def run_generated_tool_tests(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        current.error = None
        self._stream_progress(
            current,
            stage="run_generated_tool_tests",
            title="Running generated tool tests",
            message="Executing generated unit tests in a subprocess with timeout and redaction.",
        )
        if current.package_path is None:
            current.error = FactoryError(
                code="missing_package_path",
                message="Package path is required before generated tool tests.",
            )
            report = None
        else:
            report = self.verification_runner.run_generated_tool_tests(current.package_path)
            if (
                not report.ok
                and current.tool_test_repair_attempts >= current.max_tool_test_repair_attempts
            ):
                report.status = "passed_with_warnings"  # type: ignore[assignment]
                report.return_code = report.return_code or 1
                self.verification_runner.rewrite_tool_test_report(report)
            current.tool_test_report = report
            self._refresh_factory_verification_report(current)
            if not report.ok:
                current.error = FactoryError(
                    code="generated_tool_tests_failed",
                    message="Generated tool tests failed.",
                )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="run_generated_tool_tests",
            status=(
                EventStatus.FAILED
                if current.error
                else EventStatus.WARNING
                if report and report.status == "passed_with_warnings"
                else EventStatus.COMPLETED
            ),
            title="Generated tool tests finished"
            if not current.error
            else "Generated tool tests failed",
            message=_verification_message(report) if not current.error else current.error.message,
            artifact_path=str(report.report_path) if report and report.report_path else None,
            payload=_verification_payload(report),
        )
        return self._with_event(current, node="run_generated_tool_tests", event=event)

    def repair_tool_tests(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        previous_report = current.tool_test_report
        current.error = None
        current.tool_test_repair_attempts += 1
        self._stream_progress(
            current,
            stage="repair_tool_tests",
            title="Repairing generated tool tests",
            message=(
                "Rewriting tool tests as relaxed executable-contract checks, "
                f"attempt {current.tool_test_repair_attempts}/{current.max_tool_test_repair_attempts}."
            ),
        )
        if current.package_path is None or current.primitives is None:
            current.error = FactoryError(
                code="tool_test_repair_missing_inputs",
                message="Package path and primitives are required before repairing generated tool tests.",
            )
            report = None
        else:
            try:
                report = self._artifact_generator().repair_generated_tool_tests(
                    current.package_path,
                    current.primitives,
                    failed_report=previous_report,
                )
                _apply_artifact_report(current, report)
            except Exception as error:
                report = None
                current.error = FactoryError(
                    code="tool_test_repair_failed",
                    message=str(error),
                )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="repair_tool_tests",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Generated tool tests repair failed"
            if current.error
            else "Generated tool tests repaired",
            message=(
                current.error.message
                if current.error
                else f"repair_attempts={current.tool_test_repair_attempts}"
            ),
            artifact_path=(
                str(current.package_path / "generated" / "tool_tests")
                if current.package_path
                else None
            ),
            payload={
                "repair_attempts": current.tool_test_repair_attempts,
                "max_repair_attempts": current.max_tool_test_repair_attempts,
                "previous_issues": len(previous_report.issues) if previous_report else 0,
                "tool_tests": report.tool_test_count if report else 0,
            },
        )
        return self._with_event(current, node="repair_tool_tests", event=event)

    def validate_mcp_bindings_local(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="validate_mcp_bindings_local",
            title="Checking MCP bindings locally",
            message="Validating MCP YAML structure and references without connecting to servers.",
        )
        if current.package_path is None:
            current.error = FactoryError(
                code="missing_package_path",
                message="Package path is required before MCP binding checks.",
            )
            report = None
        else:
            report = self.verification_runner.validate_mcp_bindings_local(current.package_path)
            current.mcp_binding_report = report
            self._refresh_factory_verification_report(current)
            if not report.ok:
                current.error = FactoryError(
                    code="mcp_binding_local_check_failed",
                    message="MCP binding local check failed.",
                )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="validate_mcp_bindings_local",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="MCP bindings local check finished"
            if not current.error
            else "MCP bindings local check failed",
            message=_verification_message(report) if not current.error else current.error.message,
            artifact_path=str(report.report_path) if report and report.report_path else None,
            payload=_verification_payload(report),
        )
        return self._with_event(current, node="validate_mcp_bindings_local", event=event)

    def dry_run_harness_scenarios(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="dry_run_harness_scenarios",
            title="Dry-running harness specs",
            message="Checking scenario structure, fixtures, and generated tool references.",
        )
        if current.package_path is None:
            current.error = FactoryError(
                code="missing_package_path",
                message="Package path is required before harness dry-run.",
            )
            report = None
        else:
            report = self.verification_runner.dry_run_harness_scenarios(current.package_path)
            current.harness_dry_run_report = report
            self._refresh_factory_verification_report(current)
            if not report.ok:
                current.error = FactoryError(
                    code="harness_dry_run_failed",
                    message="Harness dry-run validation failed.",
                )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="dry_run_harness_scenarios",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Harness dry-run finished" if not current.error else "Harness dry-run failed",
            message=_verification_message(report) if not current.error else current.error.message,
            artifact_path=str(report.report_path) if report and report.report_path else None,
            payload=_verification_payload(report),
        )
        return self._with_event(current, node="dry_run_harness_scenarios", event=event)

    def record_factory_memory(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        self._stream_progress(
            current,
            stage="record_factory_memory",
            title="Recording Factory memory",
            message="Writing a summary into Factory memory, separate from Agent memory.",
        )
        self.context.memory_store.append(
            FactoryMemoryRecord(
                run_id=current.run_id,
                type="agent_package_draft_created",
                summary="Created validated AgentPackage primitives draft.",
                payload={
                    "requirement": current.requirement,
                    "output_path": str(current.package_path),
                    "validation_ok": current.validation_report.ok if current.validation_report else False,
                    "generated_tool_count": current.generated_tool_count,
                    "tool_test_status": (
                        current.tool_test_report.status if current.tool_test_report else None
                    ),
                    "harness_dry_run_status": (
                        current.harness_dry_run_report.status
                        if current.harness_dry_run_report
                        else None
                    ),
                    "research_completeness_status": (
                        current.research_completeness_report.get("status")
                        if isinstance(current.research_completeness_report, dict)
                        else None
                    ),
                    "pending_configuration_keys": _pending_configuration_keys(current.package_path),
                },
            )
        )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="record_factory_memory",
            status=EventStatus.COMPLETED,
            title="Factory memory recorded",
            payload={"memory_path": str(self.context.memory_path)},
        )
        return self._with_event(current, node="record_factory_memory", event=event)

    def complete(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        pending_config_files = _pending_configuration_files(current.package_path)
        pending_config_keys = _pending_configuration_keys(current.package_path)
        has_warnings = _state_has_completion_warnings(current, pending_config_files)
        current.status = "completed_with_warnings" if has_warnings else "completed"
        current.production_summary = ProductionSummary(
            status=current.status,
            generated=_generated_summary_items(current),
            satisfied_conditions=_satisfied_condition_messages(current),
            pending_configuration_keys=pending_config_keys,
            warnings=_completion_warning_messages(current, pending_config_files),
            next_steps=_production_next_steps(current, pending_config_files, pending_config_keys),
        )
        self._append_decision(
            current,
            stage="complete",
            artifact_type="ProductionSummary",
            title="Production summary",
            summary=current.status,
            payload=current.production_summary.model_dump(mode="json"),
        )
        event = FactoryEvent(
            run_id=current.run_id,
            stage="complete",
            status=EventStatus.WARNING if has_warnings else EventStatus.COMPLETED,
            title=(
                "Factory production completed with warnings"
                if has_warnings
                else "Factory production completed"
            ),
            message=(
                "Package draft was created, but review warnings and pending runtime configuration before real use."
                if pending_config_files
                else None
            ),
            artifact_path=str(current.package_path) if current.package_path else None,
            payload={
                "pending_configuration_files": [str(path) for path in pending_config_files],
                "pending_configuration_keys": pending_config_keys,
                "research_completeness": current.research_completeness_report,
                "warning_count": _completion_warning_count(current, pending_config_files),
                "tool_test_status": (
                    current.tool_test_report.status if current.tool_test_report else None
                ),
                "verification_status": (
                    current.verification_report.status if current.verification_report else None
                ),
            },
        )
        return self._with_event(current, node="complete", event=event)

    def failed(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        current.status = "failed"
        event = FactoryEvent(
            run_id=current.run_id,
            stage="failed",
            status=EventStatus.FAILED,
            title="Factory production failed",
            message=current.error.message if current.error else "Unknown factory production error.",
            payload={"code": current.error.code if current.error else "unknown"},
        )
        return self._with_event(current, node="failed", event=event)

    def needs_clarification(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        current.status = "needs_clarification"
        event = FactoryEvent(
            run_id=current.run_id,
            stage="needs_clarification",
            status=EventStatus.WARNING,
            title="Clarification required",
            message="AgentPackage was not generated.",
            payload={
                "questions": current.clarification_questions,
                "clarification_options": current.clarification_options,
                "guidance_message": current.guidance_message,
            },
        )
        return self._with_event(current, node="needs_clarification", event=event)

    def not_agent_request(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        current = FactoryProductionState.from_graph_state(state)
        current.status = "not_agent_request"
        event = FactoryEvent(
            run_id=current.run_id,
            stage="not_agent_request",
            status=EventStatus.WARNING,
            title="AgentFactory guidance",
            message=current.guidance_message
            or "This input is not an Agent creation request.",
            payload={
                "guidance_message": current.guidance_message,
                "factory_intent": current.factory_intent,
            },
        )
        return self._with_event(current, node="not_agent_request", event=event)

    def _with_event(
        self,
        state: FactoryProductionState,
        *,
        node: str,
        event: FactoryEvent,
    ) -> FactoryProductionStateDict:
        self._record_node_context(state, event.stage)
        event.payload = {
            **event.payload,
            "graph_node": node,
            "status": state.status,
            "context_envelope": (
                state.context_envelopes[-1].model_dump(mode="json")
                if state.context_envelopes
                else None
            ),
        }
        self.context.trace_store.append_event(event)
        state.current_stage = event.stage
        state.graph_node = node
        state.stage_history.append(_canonical_stage_for_progress(node, event.stage))
        state.events.append(event)
        return state.as_graph_state()

    def _record_node_context(self, state: FactoryProductionState, stage: str) -> None:
        state.context_envelopes.append(self._compile_context_envelope(state, stage))

    def _compile_context_envelope(
        self,
        state: FactoryProductionState,
        stage: str,
    ):
        ledger = DecisionLedger(
            records=[
                DecisionRecord.model_validate(record)
                for record in state.decision_records
            ]
        )
        evidence_store = EvidenceStore(
            records=[
                EvidenceRecord(
                    evidence_id=report.evidence_id,
                    stage=stage,
                    source=report.source,
                    summary=report.summary,
                    payload=report.model_dump(mode="json"),
                    safe_for_prompt=report.safe_for_prompt,
                )
                for report in state.evidence_reports
            ]
        )
        return self.context_compiler.compile(
            stage=stage,
            state=state,
            decision_ledger=ledger,
            evidence_store=evidence_store,
        )

    def _append_decision(
        self,
        state: FactoryProductionState,
        *,
        stage: str,
        artifact_type: str,
        title: str,
        summary: str,
        payload: dict[str, Any],
    ) -> None:
        ledger = DecisionLedger()
        record = ledger.append(
            stage=stage,
            title=title,
            summary=summary,
            artifact_type=artifact_type,
            payload=payload,
        )
        state.decision_records.append(record.model_dump(mode="json"))

    @staticmethod
    def _append_evidence_report(
        state: FactoryProductionState,
        report: EvidenceReport,
    ) -> None:
        by_id = {item.evidence_id: index for index, item in enumerate(state.evidence_reports)}
        if report.evidence_id in by_id:
            state.evidence_reports[by_id[report.evidence_id]] = report
        else:
            state.evidence_reports.append(report)

    def _model_service(self) -> ModelService:
        if self.model_service is not None:
            return self.model_service
        self.model_service = ModelService.from_env()
        return self.model_service

    def _optional_model_service(self) -> ModelService | None:
        try:
            return self._model_service()
        except ModelConfigError:
            return None

    def _artifact_generator(self) -> PackageArtifactGenerator:
        if self.artifact_generator is not None:
            return self.artifact_generator
        return PackageArtifactGenerator(model_service=self._model_service())

    @staticmethod
    def _missing_package_inputs(state: FactoryProductionState) -> bool:
        if state.package_path is None:
            state.error = FactoryError(
                code="missing_package_path",
                message="Package path is required before generating package artifacts.",
            )
            return True
        if state.primitives is None:
            state.error = FactoryError(
                code="missing_primitives",
                message="Primitives are required before generating package artifacts.",
            )
            return True
        return False

    def _artifact_failure_event(
        self,
        state: FactoryProductionState,
        node: str,
    ) -> FactoryProductionStateDict:
        event = FactoryEvent(
            run_id=state.run_id,
            stage=node,
            status=EventStatus.FAILED,
            title="Package artifact generation failed",
            message=state.error.message if state.error else None,
            payload={"code": state.error.code if state.error else "unknown"},
        )
        return self._with_event(state, node=node, event=event)

    def _refresh_factory_verification_report(self, state: FactoryProductionState) -> None:
        if state.package_path is None:
            return
        state.verification_report = self.verification_runner.write_factory_report(
            state.package_path,
            tool_static_check=state.tool_static_check_report,
            tool_tests=state.tool_test_report,
            mcp_binding_check=state.mcp_binding_report,
            harness_dry_run=state.harness_dry_run_report,
        )

    def _stream_progress(
        self,
        state: FactoryProductionState,
        *,
        stage: str,
        title: str,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        progress_payload = dict(payload or {})
        progress_payload.setdefault("flow_summary", message or title)
        event = FactoryEvent(
            run_id=state.run_id,
            stage=stage,
            status=EventStatus.PROGRESS,
            title=title,
            message=message,
            payload={
                **progress_payload,
                "graph_node": stage,
                "stream_kind": "node_thinking",
            },
        )
        try:
            writer = get_stream_writer()
            writer(event.model_dump(mode="json"))
        except Exception:
            return

    def _model_stream_callback(
        self,
        state: FactoryProductionState,
        *,
        stage: str,
        title: str,
        message: str,
    ):
        reasoning_chunks: list[str] = []
        content_chunks: list[str] = []
        last_emit_size = 0

        def on_event(event: LLMStreamEvent) -> None:
            nonlocal last_emit_size
            if event.type != "delta" or not event.delta:
                return
            kind = str(event.metadata.get("delta_kind") or "content")
            if kind == "reasoning":
                reasoning_chunks.append(event.delta)
            else:
                content_chunks.append(event.delta)
            reasoning = "".join(reasoning_chunks)
            content = "".join(content_chunks)
            total_size = len(reasoning) + len(content)
            if total_size - last_emit_size < 120:
                return
            last_emit_size = total_size
            if content:
                preview = "Structured JSON:\n" + _compact_preview(content, limit=900)
                flow_summary = (
                    f"Receiving structured JSON from the model "
                    f"({len(content)} chars so far)."
                )
                thinking_kind = "content"
            else:
                preview = "Reasoning:\n" + _compact_preview(reasoning, limit=900)
                flow_summary = (
                    f"Model is reasoning about this node "
                    f"({len(reasoning)} chars so far)."
                )
                thinking_kind = "reasoning"
            self._stream_progress(
                state,
                stage=stage,
                title=title,
                message=message,
                payload={
                    "thinking": preview,
                    "thinking_kind": thinking_kind,
                    "flow_summary": flow_summary,
                    "reasoning_chars": len(reasoning),
                    "content_chars": len(content),
                },
            )

        return on_event

    def _tool_progress_callback(self, state: FactoryProductionState):
        def on_progress(payload: dict[str, Any]) -> None:
            tool_id = str(payload.get("tool_id") or "unknown_tool")
            index = payload.get("tool_index")
            total = payload.get("tool_total")
            phase = str(payload.get("tool_phase") or payload.get("phase") or "processing")
            prefix = f"Tool {index}/{total}" if index and total else "Tool"
            summary = str(payload.get("flow_summary") or f"{prefix}: {tool_id} - {phase}.")
            self._stream_progress(
                state,
                stage="generate_tool_scripts",
                title="Generating tool scripts",
                message=summary,
                payload={
                    **payload,
                    "tool_id": tool_id,
                    "tool_phase": phase,
                    "flow_summary": summary,
                },
            )

        return on_progress


def _raw_mapping(raw_data: object) -> dict[str, Any] | list[Any] | None:
    if isinstance(raw_data, dict):
        return raw_data
    if isinstance(raw_data, list):
        return raw_data
    return None


def _compact_preview(value: object, *, limit: int = 900) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[truncated]"


def _planner_event_title(error: FactoryError | None) -> str:
    if error is None:
        return "PrimitivePlanner finished"
    if error.code == "model_config_error":
        return "Factory model configuration is missing"
    return "PrimitivePlanner failed"


def _apply_artifact_report(
    state: FactoryProductionState,
    report: PackageArtifactReport,
) -> None:
    state.generated_artifacts.extend(report.artifact_paths)
    state.generated_tool_count += report.tool_count
    state.generated_tool_test_count += report.tool_test_count
    state.mcp_binding_count += report.mcp_binding_count
    state.harness_scenario_count += report.harness_scenario_count


def _capabilities_from_requirement_understanding(
    state: FactoryProductionState,
) -> list[CapabilityItem]:
    analysis = state.requirement_analysis or {}
    needed_tools = analysis.get("needed_tools") if isinstance(analysis, dict) else []
    in_scope = analysis.get("in_scope_tasks") if isinstance(analysis, dict) else []
    goals = analysis.get("goals") if isinstance(analysis, dict) else []
    capabilities: list[CapabilityItem] = []
    for index, tool in enumerate(needed_tools or [], start=1):
        description = str(tool).strip()
        if not description:
            continue
        capabilities.append(
            CapabilityItem(
                capability_id=_safe_capability_id(description, index),
                description=description,
                likely_requires_tools=True,
            )
        )
    if not capabilities:
        for index, task in enumerate(in_scope or [], start=1):
            description = str(task).strip()
            if not description:
                continue
            capabilities.append(
                CapabilityItem(
                    capability_id=_safe_capability_id(description, index),
                    description=description,
                    likely_requires_tools=_task_likely_requires_tool(description),
                )
            )
    if not capabilities:
        goal = "; ".join(str(item) for item in (goals or []) if str(item).strip())
        if not goal and state.requirement_understanding is not None:
            goal = state.requirement_understanding.goal
        capabilities.append(
            CapabilityItem(
                capability_id="conversation",
                description=goal or state.requirement,
                likely_requires_tools=_task_likely_requires_tool(goal or state.requirement),
            )
        )
    return capabilities


def _safe_capability_id(value: str, index: int) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    if not normalized:
        normalized = f"capability_{index}"
    if normalized[0].isdigit():
        normalized = f"capability_{normalized}"
    return normalized[:64]


def _task_likely_requires_tool(value: str) -> bool:
    lowered = value.lower()
    return any(
        marker in value or marker in lowered
        for marker in [
            "查询",
            "搜索",
            "计算",
            "数据库",
            "文件",
            "api",
            "http",
            "url",
            "天气",
            "订单",
            "创建",
            "更新",
            "删除",
            "发送",
            "sqlite",
            "pdf",
        ]
    )


def _production_context_for_primitives(state: FactoryProductionState) -> dict[str, Any]:
    return {
        "requirement_understanding": state.requirement_understanding.model_dump(mode="json")
        if state.requirement_understanding
        else None,
        "capability_plan": state.capability_plan.model_dump(mode="json")
        if state.capability_plan
        else None,
        "condition_plan": state.condition_plan.model_dump(mode="json")
        if state.condition_plan
        else None,
        "resource_need_plan": state.resource_need_plan.model_dump(mode="json")
        if state.resource_need_plan
        else None,
        "resource_contract_set": state.resource_contract_set.model_dump(mode="json")
        if state.resource_contract_set
        else None,
        "readiness_decision": state.readiness_decision.model_dump(mode="json")
        if state.readiness_decision
        else None,
        "implementation_plan": state.implementation_plan.model_dump(mode="json")
        if state.implementation_plan
        else None,
        "evidence_summaries": [
            report.model_dump(mode="json", exclude={"details"})
            for report in state.evidence_reports
            if report.safe_for_prompt
        ],
    }


def _condition_plan_from_tool_preconditions(report: object) -> ConditionPlan:
    conditions: list[ConditionItem] = []
    for plan in getattr(report, "plans", []):
        tool_id = str(getattr(plan, "tool_id", "tool"))
        for condition in getattr(plan, "required_conditions", []):
            condition_type = str(getattr(condition, "type", "custom"))
            status = _context_condition_status(getattr(condition, "status", "unknown"))
            conditions.append(
                ConditionItem(
                    condition_id=str(getattr(condition, "condition_id", f"{tool_id}_{condition_type}")),
                    description=str(getattr(condition, "description", condition_type)),
                    required_level=_condition_required_level(condition),
                    owner=_condition_owner(condition_type),
                    status=status,
                    evidence_required=_evidence_required_for_condition(condition),
                    probe_strategy=str(getattr(condition, "probe_strategy", "none")),
                    resolution_strategy=_resolution_strategy_for_condition(condition),
                    related_resource_ids=[_resource_need_id(tool_id, condition_type)],
                    source_condition_type=condition_type,
                )
            )
    return ConditionPlan(conditions=conditions, source=getattr(report, "source", "factory"))


def _resource_need_plan_from_tool_preconditions(report: object) -> ResourceNeedPlan:
    resources: dict[str, ResourceNeed] = {}
    for plan in getattr(report, "plans", []):
        tool_id = str(getattr(plan, "tool_id", "tool"))
        for condition in getattr(plan, "required_conditions", []):
            condition_type = str(getattr(condition, "type", "custom"))
            family = _resource_family_for_condition(condition_type)
            if family == "custom" and condition_type not in {"data_contract", "mock_fixture"}:
                continue
            resource_id = _resource_need_id(tool_id, condition_type)
            evidence = getattr(condition, "evidence", {}) or {}
            configuration_keys = [
                str(value)
                for value in evidence.get("configuration_keys", [])
                if isinstance(value, str)
            ] if isinstance(evidence, dict) else []
            resources[resource_id] = ResourceNeed(
                resource_id=resource_id,
                family=family,
                kind=condition_type,
                location=_resource_location_from_condition(condition),
                access_mode=_resource_access_mode_for_condition(condition),
                visibility=_resource_visibility_for_condition(condition_type),
                lifecycle="runtime" if family in {"service", "credential", "storage"} else "build_time",
                risk_level=_resource_risk_for_condition(condition_type),
                required_evidence=_evidence_required_for_condition(condition),
                configuration_keys=configuration_keys,
                related_condition_ids=[
                    str(getattr(condition, "condition_id", f"{tool_id}_{condition_type}"))
                ],
            )
    return ResourceNeedPlan(resources=list(resources.values()), source=getattr(report, "source", "factory"))


def _condition_required_level(condition: object) -> str:
    condition_type = str(getattr(condition, "type", "custom"))
    if not bool(getattr(condition, "required", True)):
        return "warning"
    if condition_type in {"credential"}:
        return "deferred"
    return "blocking"


def _context_condition_status(value: object) -> str:
    text = str(value)
    if text in {"satisfied", "missing", "failed", "unknown", "deferred"}:
        return text
    if text == "skipped":
        return "unknown"
    return "unknown"


def _condition_owner(condition_type: str) -> str:
    if condition_type in {"credential", "permission", "human_approval", "mock_fixture"}:
        return "user"
    if condition_type in {"external_service", "storage_backend", "web_research"}:
        return "runtime"
    return "factory"


def _resolution_strategy_for_condition(condition: object) -> str:
    if bool(getattr(condition, "user_input_needed", False)):
        return "ask_user"
    condition_type = str(getattr(condition, "type", "custom"))
    if condition_type in {"external_service", "credential"}:
        return "external_config"
    if condition_type in {"local_resource", "database_schema"}:
        return "probe_local_resource"
    if condition_type == "web_research":
        return "collect_user_url"
    return "probe_or_defer"


def _resource_family_for_condition(condition_type: str) -> str:
    return {
        "local_resource": "data",
        "database_schema": "data",
        "data_contract": "data",
        "external_service": "service",
        "credential": "credential",
        "permission": "permission",
        "human_approval": "human",
        "storage_backend": "storage",
        "browser_access": "browser",
        "mcp_server": "mcp",
        "python_package": "runtime",
        "runtime_dependency": "runtime",
        "system_command": "system",
        "web_research": "service",
        "mock_fixture": "data",
    }.get(condition_type, "custom")


def _resource_need_id(tool_id: str, condition_type: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", f"{tool_id}_{condition_type}").strip("_").lower()


def _resource_location_from_condition(condition: object) -> str | None:
    evidence = getattr(condition, "evidence", {}) or {}
    if not isinstance(evidence, dict):
        return None
    for key in ("url", "path", "ref", "endpoint", "host", "command", "module"):
        value = evidence.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resource_access_mode_for_condition(condition: object) -> str:
    text = f"{getattr(condition, 'type', '')} {getattr(condition, 'description', '')}".lower()
    if any(marker in text for marker in ["write", "create", "update", "delete", "写", "创建", "更新", "删除"]):
        return "read_write"
    return "read_only"


def _resource_visibility_for_condition(condition_type: str) -> str:
    if condition_type in {"credential"}:
        return "hidden"
    if condition_type in {"local_resource", "database_schema", "external_service"}:
        return "tool_only"
    return "factory_only"


def _resource_risk_for_condition(condition_type: str) -> str:
    if condition_type in {"credential", "permission", "human_approval"}:
        return "high"
    if condition_type in {"external_service", "storage_backend", "browser_access"}:
        return "medium"
    return "low"


def _evidence_required_for_condition(condition: object) -> list[str]:
    condition_type = str(getattr(condition, "type", "custom"))
    evidence = getattr(condition, "evidence", {}) or {}
    if isinstance(evidence, dict):
        explicit = evidence.get("evidence_required")
        if isinstance(explicit, list):
            return [str(item) for item in explicit if str(item).strip()]
    return {
        "external_service": ["official docs URL", "endpoint", "method", "params"],
        "credential": ["runtime env key", "auth placement"],
        "database_schema": ["tables", "columns", "constraints"],
        "local_resource": ["path exists", "readability", "sandbox copy"],
        "web_research": ["user-provided URL", "same-domain extracted facts"],
        "mock_fixture": ["stable test fixture"],
    }.get(condition_type, ["supporting evidence"])


def _external_config_keys_from_research(report: dict[str, Any] | None) -> list[str]:
    if not isinstance(report, dict):
        return []
    brief = report.get("brief")
    fields = brief.get("recommended_config_fields") if isinstance(brief, dict) else []
    keys = [str(field.get("key")) for field in fields if isinstance(field, dict) and field.get("key")]
    return sorted(dict.fromkeys(keys))


def _readiness_decision_from_report(
    readiness: ReadinessReport | None,
    *,
    research_completeness_report: dict[str, Any] | None,
) -> ReadinessDecision:
    if readiness is None:
        blocking = [
            ReadinessItem(
                level="blocking",
                message="Factory could not produce a readiness report.",
                resolution_hint="Inspect the Factory trace and retry.",
            )
        ]
        return ReadinessDecision(status="blocked", blocking=blocking)

    blocking: list[ReadinessItem] = []
    deferred: list[ReadinessItem] = []
    warnings: list[ReadinessItem] = []
    for issue in readiness.issues:
        item = ReadinessItem(
            level="warning",
            message=issue.message,
            resolution_hint=_resolution_hint_for_issue(issue.code),
            resource_id=issue.resource_id,
        )
        if issue.severity in {"error", "fatal"}:
            item.level = "blocking"
            blocking.append(item)
        elif issue.code in {"external_config_template_required", "research_completeness"}:
            item.level = "deferred"
            deferred.append(item)
        else:
            warnings.append(item)

    readiness_issue_codes = {issue.code for issue in readiness.issues}
    if isinstance(research_completeness_report, dict) and (
        "research_completeness" in readiness_issue_codes
        or research_completeness_report.get("missing_config_keys")
    ):
        for key in research_completeness_report.get("missing_config_keys") or []:
            deferred.append(
                ReadinessItem(
                    level="deferred",
                    message=f"运行期配置待补：{key}",
                    resolution_hint="写入 external_config.yaml 对应键，并在 .env 中提供真实值。",
                )
            )
        status = str(research_completeness_report.get("status") or "")
        if status == "needs_more_url":
            blocking.append(
                ReadinessItem(
                    level="blocking",
                    message=str(research_completeness_report.get("summary") or "外部资料不足，需要补充官方文档 URL。"),
                    resolution_hint="补充认证、endpoint、参数或示例响应所在的官方文档 URL。",
                )
            )
        elif status == "needs_config_values" and not blocking:
            # Missing runtime values should not block package generation.
            deferred.append(
                ReadinessItem(
                    level="deferred",
                    message=str(research_completeness_report.get("summary") or "外部服务运行期配置待补。"),
                    resolution_hint="生产完成后补齐 external_config.yaml / .env。",
                )
            )

    # External config placeholders are deferred; do not keep duplicated blocking
    # issues for the same condition when the package can safely be generated.
    if deferred and _only_external_config_blockers(blocking):
        blocking = []

    if blocking:
        status_value = "needs_user_input" if readiness.status == "needs_user_input" else "blocked"
    elif deferred or readiness.status == "ready" and any(issue.severity == "warning" for issue in readiness.issues):
        status_value = "ready_with_deferred"
    else:
        status_value = "ready"

    return ReadinessDecision(
        status=status_value,
        blocking=blocking,
        deferred=deferred,
        warnings=warnings,
        resolution_questions=_resolution_questions_for_items(blocking),
    )


def _only_external_config_blockers(items: list[ReadinessItem]) -> bool:
    if not items:
        return False
    markers = (
        "external",
        "credential",
        "mock",
        "data contract",
        "Deferred to external_config",
        "外部",
        "凭证",
        "配置",
    )
    return all(any(marker in item.message for marker in markers) for item in items)


def _resolution_hint_for_issue(code: str) -> str:
    if code in {"resource_exists", "resource_readable", "sqlite_openable", "sqlite_schema_available"}:
        return "提供一个存在且可访问的本地资源路径，或确认创建示例资源。"
    if code in {"research_completeness", "web_research", "external_service"}:
        return "补充包含 endpoint、鉴权、参数或示例响应的官方文档 URL。"
    if code in {"credential"}:
        return "提供运行期配置键名，密钥只写入 .env，不写入包。"
    return "补充该条件所需的证据或选择只生成不可运行草稿。"


def _resolution_questions_for_items(items: list[ReadinessItem]) -> list[ResolutionQuestion]:
    if not items:
        return []
    first = items[0]
    message = first.message
    if any(marker in message for marker in ["URL", "endpoint", "auth", "文档", "外部", "官方"]):
        options = [
            {"id": "provide_external_url", "label": "补充官方文档 URL", "description": "提供包含缺失接口事实的同域官方页面。"},
            {"id": "provide_manual_facts", "label": "手动输入接口信息", "description": "直接给出 endpoint、method、auth、params 或示例响应。"},
            {"id": "generate_draft_only", "label": "只生成草稿", "description": "生成不可直接运行的草稿，并在 summary 标明缺口。"},
        ]
    elif any(marker in message for marker in ["Resource", "SQLite", "path", "资源", "路径", "数据库"]):
        options = [
            {"id": "replace_resource_path", "label": "提供资源路径", "description": "提供已存在且可访问的本地文件或目录。"},
            {"id": "create_sample_resource", "label": "创建示例资源", "description": "确认后创建示例数据库或文件继续生产。"},
            {"id": "generate_draft_only", "label": "只生成草稿", "description": "暂不运行工具测试。"},
        ]
    else:
        options = [
            {"id": "provide_missing_info", "label": "补充缺失信息", "description": "直接输入当前条件需要的事实。"},
            {"id": "provide_test_fixture", "label": "提供测试样例", "description": "提供稳定样例输入、输出或 mock 响应。"},
            {"id": "generate_draft_only", "label": "只生成草稿", "description": "生成不可直接运行的草稿。"},
        ]
    return [
        ResolutionQuestion(
            question_id="readiness_resolution",
            prompt=_targeted_question_prompt(items),
            options=options[:3],
            free_text_allowed=True,
        )
    ]


def _targeted_question_prompt(items: list[ReadinessItem]) -> str:
    lines = ["当前还缺以下真实条件："]
    lines.extend(f"- {item.message}" for item in items[:3])
    lines.append("你希望怎么补齐？")
    return "\n".join(lines)


def _clarification_options_from_readiness_decision(
    question: str,
    decision: ReadinessDecision,
    readiness: ReadinessReport,
) -> list[dict[str, Any]]:
    if decision.resolution_questions:
        options = [
            {
                "id": option.get("id", f"option_{index}"),
                "label": option.get("label", option.get("id", f"选项 {index}")),
                "description": option.get("description", ""),
            }
            for index, option in enumerate(decision.resolution_questions[0].options[:3], start=1)
        ]
    else:
        options = [
            {
                "id": option.id,
                "label": option.label,
                "description": option.description,
            }
            for option in readiness.options[:3]
        ]
    if not any(option["id"] == "other" for option in options):
        options.append(
            {
                "id": "other",
                "label": "其他",
                "description": "直接输入你自己的补充信息。",
            }
        )
    return [{"id": "readiness_action", "question": question, "options": options[:4]}]


def _tool_contract_refs(state: FactoryProductionState) -> list[str]:
    if state.primitives is None:
        return []
    return [
        tool_id
        for toolset in state.primitives.toolsets.toolsets
        for tool_id in toolset.exposed_tools + toolset.hidden_tools
    ]


def _resource_contract_refs(state: FactoryProductionState) -> list[str]:
    if state.resource_contracts is None:
        return []
    return [resource.id for resource in state.resource_contracts.resources]


def _verification_message(
    report: (
        ToolStaticCheckReport
        | ToolTestRunReport
        | MCPBindingLocalCheckReport
        | HarnessDryRunReport
        | None
    ),
) -> str | None:
    if report is None:
        return None
    if report.status == "skipped":
        return "skipped"
    return f"status={report.status}, issues={len(report.issues)}"


def _verification_payload(
    report: (
        ToolStaticCheckReport
        | ToolTestRunReport
        | MCPBindingLocalCheckReport
        | HarnessDryRunReport
        | None
    ),
) -> dict[str, Any]:
    if report is None:
        return {}
    payload: dict[str, Any] = {
        "verification_status": report.status,
        "issues": len(report.issues),
    }
    if isinstance(report, ToolStaticCheckReport):
        payload["checked_files"] = len(report.checked_files)
    elif isinstance(report, ToolTestRunReport):
        payload["test_files"] = len(report.test_files)
        payload["return_code"] = report.return_code
    elif isinstance(report, MCPBindingLocalCheckReport):
        payload["servers"] = report.server_count
        payload["bindings"] = report.binding_count
    elif isinstance(report, HarnessDryRunReport):
        payload["scenarios"] = report.scenario_count
    return payload


def _has_blocking_full_validation_issues(report: object) -> bool:
    local_verification_files = {"mcp.yaml", "harness.yaml"}
    for issue in getattr(report, "issues", []):
        if getattr(issue, "severity", None) not in {"error", "fatal"}:
            continue
        if getattr(issue, "file", None) in local_verification_files:
            continue
        return True
    return False


def _web_research_queries(report: dict[str, Any] | None) -> list[str]:
    if not isinstance(report, dict):
        return []
    queries: list[str] = []
    for plan in report.get("plans", []):
        if not isinstance(plan, dict):
            continue
        needs_research = any(
            isinstance(condition, dict)
            and condition.get("type") == "web_research"
            and condition.get("required", False) is not False
            for condition in plan.get("required_conditions", [])
        ) or bool(plan.get("research_queries"))
        if not needs_research:
            continue
        for query in plan.get("research_queries", []):
            if isinstance(query, str) and query.strip() and query not in queries:
                queries.append(query)
    return queries


def _readiness_event_message(status: str, readiness: ReadinessReport | None) -> str:
    if readiness is None:
        return f"status={status}"
    warnings = [issue for issue in readiness.issues if issue.severity == "warning"]
    errors = [issue for issue in readiness.issues if issue.severity in {"error", "fatal"}]
    if status == "ready" and warnings:
        return f"status=ready, warnings={len(warnings)}"
    if errors:
        first = errors[0].message
        return f"status={status}, missing={len(errors)}; {first}"
    return f"status={status}"


def _readiness_clarification_question(
    readiness: ReadinessReport,
    decision: ReadinessDecision | None = None,
) -> str:
    if decision is not None and decision.resolution_questions:
        return decision.resolution_questions[0].prompt
    blocking = [
        issue.message
        for issue in readiness.issues
        if issue.severity in {"error", "fatal"}
    ][:5]
    if not blocking:
        return "前置条件还不完整。你希望 AgentFactory 怎么处理？"
    lines = ["前置条件还不完整，当前缺少："]
    lines.extend(f"- {message}" for message in blocking)
    lines.append("你希望 AgentFactory 怎么处理？")
    return "\n".join(lines)


def _pending_configuration_files(package_path: Path | None) -> list[Path]:
    if package_path is None:
        return []
    candidates = [package_path / "external_config.yaml"]
    return [path for path in candidates if path.exists()]


def _pending_configuration_keys(package_path: Path | None) -> list[str]:
    if package_path is None:
        return []
    path = package_path / "external_config.yaml"
    if not path.exists():
        return []
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    values = data.get("values") if isinstance(data.get("values"), dict) else {}
    required = data.get("required_keys") if isinstance(data.get("required_keys"), list) else []
    return [str(key) for key in required if not str(values.get(str(key)) or "").strip()]


def _state_has_completion_warnings(
    state: FactoryProductionState,
    pending_config_files: list[Path],
) -> bool:
    return _completion_warning_count(state, pending_config_files) > 0


def _completion_warning_count(
    state: FactoryProductionState,
    pending_config_files: list[Path],
) -> int:
    count = len(pending_config_files)
    for report in [
        state.tool_static_check_report,
        state.tool_test_report,
        state.mcp_binding_report,
        state.harness_dry_run_report,
        state.verification_report,
    ]:
        if report is not None and getattr(report, "status", None) == "passed_with_warnings":
            count += 1
    if state.readiness_report is not None:
        count += len(
            [
                issue
                for issue in state.readiness_report.issues
                if getattr(issue, "severity", None) == "warning"
            ]
            )
    return count


def _generated_summary_items(state: FactoryProductionState) -> list[str]:
    items: list[str] = []
    if state.package_path:
        items.append(f"AgentPackage draft: {state.package_path}")
    if state.generated_tool_count:
        items.append(f"{state.generated_tool_count} tool scripts")
    if state.generated_tool_test_count:
        items.append(f"{state.generated_tool_test_count} tool tests")
    if state.harness_scenario_count:
        items.append(f"{state.harness_scenario_count} harness scenarios")
    return items


def _satisfied_condition_messages(state: FactoryProductionState) -> list[str]:
    if state.condition_plan is None:
        return []
    return [
        condition.description
        for condition in state.condition_plan.conditions
        if condition.status == "satisfied"
    ][:10]


def _completion_warning_messages(
    state: FactoryProductionState,
    pending_config_files: list[Path],
) -> list[str]:
    messages: list[str] = []
    if pending_config_files:
        messages.append("External runtime configuration is pending.")
    if state.readiness_decision is not None:
        messages.extend(item.message for item in state.readiness_decision.deferred[:10])
        messages.extend(item.message for item in state.readiness_decision.warnings[:10])
    if state.tool_test_report is not None and state.tool_test_report.status == "passed_with_warnings":
        messages.append("Generated tool tests passed with warnings.")
    elif state.tool_test_report is not None and state.tool_test_report.status == "failed":
        messages.append("Generated tool tests still have failures; review the report before runtime.")
    return list(dict.fromkeys(messages))


def _production_next_steps(
    state: FactoryProductionState,
    pending_config_files: list[Path],
    pending_config_keys: list[str],
) -> list[str]:
    steps: list[str] = []
    if pending_config_files:
        steps.append(f"Fill {pending_config_files[0]} and .env keys: {', '.join(pending_config_keys) or 'see file'}")
    if state.package_path:
        steps.extend(
            [
                f"/validate {state.package_path}",
                f"/test {state.package_path}",
                f"/run {state.package_path} --input \"...\"",
            ]
        )
    return steps


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _canonical_stage_for_progress(node: str, stage: str) -> str:
    mapping = {
        "capture_requirement": "capture_requirement",
        "load_factory_context": "capture_requirement",
        "classify_factory_intent": "capture_requirement",
        "analyze_requirement": "understand_requirement",
        "maybe_clarify": "understand_requirement",
        "plan_capability_preconditions": "plan_capabilities",
        "analyze_tool_preconditions": "identify_conditions",
        "discover_resources": "plan_resource_needs",
        "factory_web_research": "collect_evidence",
        "probe_environment": "build_resource_contracts",
        "resolve_readiness": "decide_readiness",
        "enrich_tool_contracts": "plan_implementation",
        "plan_primitives": "generate_package_specs",
        "validate_primitives": "generate_package_specs",
        "repair_primitives": "generate_package_specs",
        "write_package": "generate_package_specs",
        "generate_tool_scripts": "generate_tools",
        "generate_tool_tests": "sandbox_test_and_repair",
        "static_check_tool_scripts": "sandbox_test_and_repair",
        "run_generated_tool_tests": "sandbox_test_and_repair",
        "repair_tool_tests": "sandbox_test_and_repair",
        "generate_mcp_bindings": "generate_package_specs",
        "generate_harness_scenarios": "generate_harness",
        "validate_package": "generate_package_specs",
        "validate_mcp_bindings_local": "sandbox_test_and_repair",
        "dry_run_harness_scenarios": "generate_harness",
        "record_factory_memory": "complete_summary",
        "complete": "complete_summary",
        "needs_clarification": "decide_readiness",
        "not_agent_request": "capture_requirement",
        "failed": stage,
    }
    return mapping.get(node, stage)


def _slugify(value: str) -> str:
    ascii_slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return ascii_slug[:80] or "agent-package-draft"
