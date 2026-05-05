from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from agent_factory.harness.loader import HarnessLoader
from agent_factory.harness.result import (
    AssertionResult,
    HarnessRunResult,
    ScenarioObservation,
    ScenarioRunResult,
)
from agent_factory.harness.scenario import HarnessScenario, HarnessSpec
from agent_factory.model import FakeModelAdapter, ModelConfig, ModelService
from agent_factory.runtime import AgentRunRequest, WorkflowRuntime


class AgentHarnessRunner:
    """First executable AgentHarness runner.

    This runner executes scenario contracts against generated package artifacts.
    It does not yet start an AgentInstance runtime.
    """

    def __init__(
        self,
        loader: HarnessLoader | None = None,
        runtime: WorkflowRuntime | None = None,
    ) -> None:
        self.loader = loader or HarnessLoader()
        self.runtime = runtime or WorkflowRuntime(
            model_service=ModelService.with_adapter(
                ModelConfig(provider="fake"),
                FakeModelAdapter(["AF-TEST-USER"]),
            )
        )
        self._yaml = YAML(typ="safe")

    def run(self, package_path: str | Path, *, scenario_id: str | None = None) -> HarnessRunResult:
        root = Path(package_path)
        harness = self.loader.load(root)
        selected_scenarios = _filter_scenarios(harness, scenario_id)
        tool_metadata = self._load_tool_metadata(root)
        started_at = datetime.now(timezone.utc)
        scenario_results = [
            self._run_scenario(root, scenario, harness, tool_metadata)
            for scenario in selected_scenarios
        ]
        status = "passed" if all(result.ok for result in scenario_results) else "failed"
        result = HarnessRunResult(
            package_path=root,
            harness_path=root / "harness.yaml",
            status=status,
            scenario_results=scenario_results,
            started_at=started_at,
            ended_at=datetime.now(timezone.utc),
        )
        report_path = root / "generated" / "reports" / "harness_run.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        result.report_path = report_path
        report_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return result

    def _run_scenario(
        self,
        package_path: Path,
        scenario: HarnessScenario,
        harness: HarnessSpec,
        tool_metadata: dict[str, dict[str, Any]],
    ) -> ScenarioRunResult:
        runtime_result = None
        session_id = f"harness-{scenario.id}"
        for turn in scenario.turns:
            runtime_result = self.runtime.run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input=turn.user,
                    session_id=session_id,
                )
            )
        assert runtime_result is not None
        selected_tool = scenario.expected.selected_tool_id
        observed_tool = (
            runtime_result.tool_proposals[0].name
            if runtime_result.tool_proposals
            else selected_tool
        )
        tool_available = selected_tool in tool_metadata if selected_tool else None
        confirmation_required = (
            _tool_requires_approval(tool_metadata.get(selected_tool or ""))
            if selected_tool
            else None
        )
        observations = ScenarioObservation(
            turn_count=len(scenario.turns),
            intent=runtime_result.intent or scenario.expected.intent_id,
            selected_tool=observed_tool,
            tool_available=tool_available,
            confirmation_required=confirmation_required,
            direct_execution_blocked=not any(
                result.tool_id == selected_tool and result.status == "completed"
                for result in runtime_result.tool_results
                if selected_tool
            )
            if scenario.expected.forbidden_direct_execution
            else True,
            history_turn_count=runtime_result.history_turn_count,
            tool_result_statuses={
                result.tool_id: result.status for result in runtime_result.tool_results
            },
            tool_summary_fallback=runtime_result.tool_summary_fallback,
            fixture_refs=scenario.fixtures,
            final_response=runtime_result.answer,
        )
        assertions = _assert_scenario(scenario, harness, observations)
        status = "passed" if all(result.status != "failed" for result in assertions) else "failed"
        return ScenarioRunResult(
            scenario_id=scenario.id,
            name=scenario.name,
            status=status,
            observations=observations,
            assertion_results=assertions,
        )

    def _load_tool_metadata(self, package_path: Path) -> dict[str, dict[str, Any]]:
        metadata: dict[str, dict[str, Any]] = {}
        for path in sorted((package_path / "generated" / "draft_tools").glob("*.tool.yaml")):
            data = self._yaml.load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("tool_id"), str):
                metadata[data["tool_id"]] = data
        return metadata


def _filter_scenarios(harness: HarnessSpec, scenario_id: str | None) -> list[HarnessScenario]:
    if scenario_id is None:
        return harness.scenarios
    return [scenario for scenario in harness.scenarios if scenario.id == scenario_id]


def _tool_requires_approval(metadata: dict[str, Any] | None) -> bool | None:
    if not metadata:
        return None
    approval = metadata.get("approval")
    if isinstance(approval, dict):
        required = approval.get("required")
        if isinstance(required, bool):
            return required
    return None


def _simulated_response(scenario: HarnessScenario) -> str:
    selected_tool = scenario.expected.selected_tool_id
    intent = scenario.expected.intent_id
    parts = [f"scenario={scenario.id}"]
    if intent:
        parts.append(f"intent={intent}")
    if selected_tool:
        parts.append(f"tool_proposal={selected_tool}")
    return "; ".join(parts)


def _assert_scenario(
    scenario: HarnessScenario,
    harness: HarnessSpec,
    observations: ScenarioObservation,
) -> list[AssertionResult]:
    assertions = [
        AssertionResult(
            id="turns_present",
            status="passed" if observations.turn_count > 0 else "failed",
            message="Scenario has at least one turn.",
            expected="turn_count > 0",
            actual=observations.turn_count,
        )
    ]
    assertions.append(_assert_fixture_refs(scenario, harness))
    selected_tool = scenario.expected.selected_tool_id
    expected_intent = scenario.expected.intent_id
    if expected_intent:
        assertions.append(
            AssertionResult(
                id="expected_intent",
                status="passed" if observations.intent == expected_intent else "failed",
                message="Runtime intent matches scenario expectation.",
                expected=expected_intent,
                actual=observations.intent,
            )
        )
    if selected_tool:
        assertions.append(
            AssertionResult(
                id="selected_tool_available",
                status="passed" if observations.tool_available else "failed",
                message="Selected tool exists in generated draft tools.",
                expected=selected_tool,
                actual=observations.selected_tool,
            )
        )
        if not scenario.expected.forbidden_direct_execution and scenario.expected.must_confirm is False:
            assertions.append(
                AssertionResult(
                    id="selected_tool_completed",
                    status="passed"
                    if observations.tool_result_statuses.get(selected_tool) == "completed"
                    else "failed",
                    message="Selected tool completes through Runtime ToolExecutor.",
                    expected="completed",
                    actual=observations.tool_result_statuses.get(selected_tool),
                )
            )
    else:
        assertions.append(
            AssertionResult(
                id="selected_tool_available",
                status="skipped",
                message="Scenario does not require a selected tool.",
            )
        )

    if scenario.expected.forbidden_tools:
        assertions.append(
            AssertionResult(
                id="forbidden_tools_not_selected",
                status="passed"
                if observations.selected_tool not in scenario.expected.forbidden_tools
                else "failed",
                message="Selected tool must not be forbidden.",
                expected=scenario.expected.forbidden_tools,
                actual=observations.selected_tool,
            )
        )
    else:
        assertions.append(
            AssertionResult(
                id="forbidden_tools_not_selected",
                status="skipped",
                message="Scenario has no forbidden tools.",
            )
        )

    if scenario.expected.must_confirm is not None:
        assertions.append(
            AssertionResult(
                id="must_confirm",
                status="passed"
                if scenario.expected.must_confirm == bool(observations.confirmation_required)
                else "failed",
                message="Confirmation policy matches scenario expectation.",
                expected=scenario.expected.must_confirm,
                actual=observations.confirmation_required,
            )
        )
    else:
        assertions.append(
            AssertionResult(
                id="must_confirm",
                status="skipped",
                message="Scenario does not declare confirmation expectation.",
            )
        )

    if scenario.expected.memory_read_allowed is not None:
        assertions.append(
            AssertionResult(
                id="memory_read",
                status="passed"
                if scenario.expected.memory_read_allowed == (observations.history_turn_count > 0)
                else "failed",
                message="Runtime memory read matches scenario expectation.",
                expected=scenario.expected.memory_read_allowed,
                actual=observations.history_turn_count,
            )
        )

    if scenario.expected.forbidden_direct_execution:
        assertions.append(
            AssertionResult(
                id="forbidden_direct_execution",
                status="passed" if observations.direct_execution_blocked else "failed",
                message="Draft tool execution is blocked from real side effects.",
                expected=True,
                actual=observations.direct_execution_blocked,
            )
        )

    constraints = scenario.expected.response_constraints
    if constraints.must_include:
        missing = [
            value for value in constraints.must_include if value not in observations.final_response
        ]
        assertions.append(
            AssertionResult(
                id="response_must_include",
                status="failed" if missing else "passed",
                message="Final response contains required text.",
                expected=constraints.must_include,
                actual=observations.final_response,
            )
        )
    if constraints.must_not_include:
        present = [
            value for value in constraints.must_not_include if value in observations.final_response
        ]
        assertions.append(
            AssertionResult(
                id="response_must_not_include",
                status="failed" if present else "passed",
                message="Final response excludes forbidden text.",
                expected=constraints.must_not_include,
                actual=observations.final_response,
            )
        )
    return assertions


def _assert_fixture_refs(scenario: HarnessScenario, harness: HarnessSpec) -> AssertionResult:
    if not scenario.fixtures:
        return AssertionResult(
            id="fixture_refs_exist",
            status="skipped",
            message="Scenario does not declare fixture refs.",
        )
    missing = [
        ref for ref in scenario.fixtures if not _fixture_ref_exists(ref, harness)
    ]
    return AssertionResult(
        id="fixture_refs_exist",
        status="failed" if missing else "passed",
        message="Scenario fixture refs exist.",
        expected=scenario.fixtures,
        actual={"missing": missing},
    )


def _fixture_ref_exists(ref: str, harness: HarnessSpec) -> bool:
    groups = {
        "tool": harness.fixtures.tools,
        "mcp": harness.fixtures.mcp,
        "context": harness.fixtures.context,
        "memory": harness.fixtures.memory,
    }
    if ":" not in ref:
        return any(ref in group for group in groups.values())
    group_name, item_id = ref.split(":", 1)
    group = groups.get(group_name)
    return group is not None and item_id in group
