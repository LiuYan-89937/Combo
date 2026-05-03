from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from langgraph.config import get_stream_writer
from pydantic import ValidationError

from agent_factory.core import EventStatus, FactoryEvent
from agent_factory.factory import FactoryError
from agent_factory.factory.package_artifacts import (
    PackageArtifactGenerator,
    PackageArtifactReport,
)
from agent_factory.factory.primitive_normalizer import normalize_primitives_candidate
from agent_factory.factory.requirement_analyzer import RequirementAnalyzer
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
from agent_factory.model import LLMStreamEvent, ModelConfigError, ModelService
from agent_factory.package import PackageValidator
from agent_factory.specs import AgentPackagePrimitives


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
        event = FactoryEvent(
            run_id=current.run_id,
            stage="write_package",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="YAML AgentPackage draft written" if not current.error else "Package write failed",
            message=current.error.message if current.error else None,
            artifact_path=str(current.package_path) if current.package_path else None,
            payload={"files": 9 if not current.error else 0},
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
                requirement=current.requirement,
                requirement_analysis=current.requirement_analysis,
                on_stream_event=self._model_stream_callback(
                    current,
                    stage="generate_tool_scripts",
                    title="Generating tool scripts",
                    message="Streaming model reasoning and tool code JSON.",
                ),
                on_tool_progress=self._tool_progress_callback(current),
            )
            _apply_artifact_report(current, report)
            if report.issues:
                current.error = FactoryError(
                    code="tool_script_generation_failed",
                    message="; ".join(report.issues[:3]),
                )
        except Exception as error:
            current.error = FactoryError(code="tool_script_generation_failed", message=str(error))
        event = FactoryEvent(
            run_id=current.run_id,
            stage="generate_tool_scripts",
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Tool draft scripts generated" if not current.error else "Tool draft generation failed",
            message=current.error.message if current.error else None,
            artifact_path=str(current.package_path / "generated" / "draft_tools")
            if current.package_path
            else None,
            payload={
                "tools": current.generated_tool_count,
                "issues": report.issues if "report" in locals() else [],
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
            status=EventStatus.FAILED if current.error else EventStatus.COMPLETED,
            title="Generated tool tests finished"
            if not current.error
            else "Generated tool tests failed",
            message=_verification_message(report) if not current.error else current.error.message,
            artifact_path=str(report.report_path) if report and report.report_path else None,
            payload=_verification_payload(report),
        )
        return self._with_event(current, node="run_generated_tool_tests", event=event)

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
        current.status = "completed"
        event = FactoryEvent(
            run_id=current.run_id,
            stage="complete",
            status=EventStatus.COMPLETED,
            title="Factory production completed",
            artifact_path=str(current.package_path) if current.package_path else None,
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
            payload={"questions": current.clarification_questions},
        )
        return self._with_event(current, node="needs_clarification", event=event)

    def _with_event(
        self,
        state: FactoryProductionState,
        *,
        node: str,
        event: FactoryEvent,
    ) -> FactoryProductionStateDict:
        event.payload = {
            **event.payload,
            "graph_node": node,
            "status": state.status,
        }
        self.context.trace_store.append_event(event)
        state.current_stage = event.stage
        state.graph_node = node
        state.stage_history.append(node)
        state.events.append(event)
        return state.as_graph_state()

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


def _slugify(value: str) -> str:
    ascii_slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return ascii_slug[:80] or "agent-package-draft"
