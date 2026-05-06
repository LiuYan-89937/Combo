from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.bindings.services import RuntimeServices
from agent_factory.runtime_kernel.harness.assertions import (
    AssertCheckpointCreated,
    AssertContextBuilt,
    AssertFinalAnswer,
    AssertPathContains,
    AssertPolicyBlocked,
    AssertResumeEvent,
    AssertToolCalled,
)
from agent_factory.runtime_kernel.harness.fixtures import FixtureBundle, HarnessScenario, HarnessScenarioResult
from agent_factory.runtime_kernel.kernel.facade import RuntimeKernelFacade


class HarnessBridge:
    def __init__(self, *, facade: RuntimeKernelFacade | None = None) -> None:
        self.facade = facade or RuntimeKernelFacade()

    def run_scenario(
        self,
        *,
        pattern_id: str,
        bindings: Any,
        services: RuntimeServices,
        fixture: FixtureBundle,
        scenario: HarnessScenario,
    ) -> HarnessScenarioResult:
        merged_services = services.model_copy(
            update={
                "model_service": fixture.model_service or services.model_service,
                "tool_registry": fixture.tool_registry or services.tool_registry,
                "policy_engine": fixture.policy_engine or services.policy_engine,
                "memory_engine": fixture.memory_engine or services.memory_engine,
                "knowledge_engine": fixture.knowledge_engine or services.knowledge_engine,
            }
        )
        compiled = self.facade.compile(pattern_id=pattern_id, bindings=bindings, services=merged_services)
        result_state = self.facade.run(compiled, user_input=scenario.input_text)
        interrupted_state = None
        if scenario.resume_after_interrupt and result_state.observability.debug_refs:
            checkpoint_refs = [item for item in result_state.observability.debug_refs if item.get("kind") == "checkpoint"]
            if checkpoint_refs:
                interrupted_state = result_state
                checkpoint_id = checkpoint_refs[-1]["checkpoint_id"]
                result_state = self.facade.resume(compiled, checkpoint_id=checkpoint_id)
                result_state.observability.debug_refs = [
                    *interrupted_state.observability.debug_refs,
                    *result_state.observability.debug_refs,
                ]
                result_state.observability.events = [
                    *interrupted_state.observability.events,
                    *result_state.observability.events,
                ]
        assertion_results = []
        for raw in scenario.assertions:
            kind = raw.get("type")
            if kind == "path_contains":
                assertion = AssertPathContains(raw.get("expected_node_ids") or [])
                assertion_results.append(assertion.check(event_log=result_state.observability.events))
            elif kind == "tool_called":
                assertion = AssertToolCalled(str(raw.get("tool_id") or ""))
                assertion_results.append(assertion.check(final_state=result_state))
            elif kind == "final_answer":
                assertion = AssertFinalAnswer(str(raw.get("expected") or ""))
                assertion_results.append(assertion.check(final_state=result_state))
            elif kind == "policy_blocked":
                assertion = AssertPolicyBlocked()
                assertion_results.append(assertion.check(final_state=result_state))
            elif kind == "context_built":
                assertion = AssertContextBuilt(str(raw.get("context_key") or ""))
                assertion_results.append(assertion.check(final_state=result_state))
            elif kind == "checkpoint_created":
                assertion = AssertCheckpointCreated()
                assertion_results.append(assertion.check(final_state=result_state))
            elif kind == "resume_event":
                assertion = AssertResumeEvent()
                assertion_results.append(assertion.check(event_log=result_state.observability.events))
        ok = all(item.get("ok") for item in assertion_results) if assertion_results else True
        return HarnessScenarioResult(
            scenario_id=scenario.scenario_id,
            status="passed" if ok else "failed",
            assertion_results=assertion_results,
            final_answer=result_state.conversation.final_answer,
            event_log=result_state.observability.events,
            trace_summary=(
                merged_services.observability_manager.summary_for(result_state.run.run_id).model_dump(mode="json")
                if merged_services.observability_manager.summary_for(result_state.run.run_id)
                else None
            ),
        )
