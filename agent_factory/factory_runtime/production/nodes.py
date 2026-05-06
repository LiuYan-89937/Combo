from __future__ import annotations

from typing import Any

from agent_factory.core import EventStatus, FactoryEvent
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.factory_runtime.production.policies import FactoryNodeAccessPolicy
from agent_factory.factory_runtime.production.state import (
    FactoryProductionState,
    FactoryProductionStateDict,
)


FACTORY_STAGE_SEQUENCE = [
    "capture_requirement",
    "understand_requirement",
    "plan_capabilities",
    "identify_conditions",
    "plan_resource_needs",
    "collect_evidence",
    "build_resource_contracts",
    "decide_readiness",
    "plan_implementation",
    "generate_package_specs",
    "generate_tools",
    "sandbox_test_and_repair",
    "generate_harness",
    "complete_summary",
]


FACTORY_STAGE_TITLES = {
    "capture_requirement": "Capture Requirement",
    "understand_requirement": "Understand Requirement",
    "plan_capabilities": "Plan Capabilities",
    "identify_conditions": "Identify Conditions",
    "plan_resource_needs": "Plan Resource Needs",
    "collect_evidence": "Collect Evidence",
    "build_resource_contracts": "Build Resource Contracts",
    "decide_readiness": "Decide Readiness",
    "plan_implementation": "Plan Implementation",
    "generate_package_specs": "Generate Package Specs",
    "generate_tools": "Generate Tools",
    "sandbox_test_and_repair": "Sandbox Test And Repair",
    "generate_harness": "Generate Harness",
    "complete_summary": "Complete Summary",
}


class FactoryProductionNodes:
    """14-stage placeholder pipeline.

    All previous internal production logic has been intentionally cleared. Each
    stage currently exists only as a shell so the graph shape and CLI flow can
    remain stable while the internals are rewritten around LangGraph/LangChain.
    """

    def __init__(
        self,
        context: FactoryRunContext,
    ) -> None:
        self.context = context
        self.node_access_policy = FactoryNodeAccessPolicy()

    def guarded(self, node_name: str):
        return self.node_access_policy.wrap(node_name, getattr(self, node_name))

    def capture_requirement(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "capture_requirement")

    def understand_requirement(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "understand_requirement")

    def plan_capabilities(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "plan_capabilities")

    def identify_conditions(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "identify_conditions")

    def plan_resource_needs(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "plan_resource_needs")

    def collect_evidence(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "collect_evidence")

    def build_resource_contracts(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "build_resource_contracts")

    def decide_readiness(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "decide_readiness")

    def plan_implementation(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "plan_implementation")

    def generate_package_specs(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "generate_package_specs")

    def generate_tools(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "generate_tools")

    def sandbox_test_and_repair(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "sandbox_test_and_repair")

    def generate_harness(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "generate_harness")

    def complete_summary(self, state: FactoryProductionStateDict) -> FactoryProductionStateDict:
        return self._run_stage(state, "complete_summary", final=True)

    def _run_stage(
        self,
        raw_state: FactoryProductionStateDict,
        stage: str,
        *,
        final: bool = False,
    ) -> FactoryProductionStateDict:
        state = FactoryProductionState.from_graph_state(raw_state)
        title = FACTORY_STAGE_TITLES[stage]
        next_stage = _next_stage(stage)

        payload: dict[str, Any] = {
            "stage": stage,
            "shell_only": True,
            "next_stage": next_stage,
        }
        message = "阶段空壳已保留，内部实现已清空，等待重写。"
        event_status = EventStatus.COMPLETED

        if state.stop_after_stage == stage and not final:
            state.status = "paused"
            state.breakpoint_details = {
                "breakpoint_stage": stage,
                "next_stage": next_stage,
                "requirement": state.requirement,
                "message": "当前只保留阶段空壳，内部实现已清空。",
            }
            payload["breakpoint_details"] = state.breakpoint_details
            message = f"已停在阶段空壳：{stage}。后续阶段未执行。"
            event_status = EventStatus.WARNING
        elif final:
            state.status = "completed"
            state.production_summary = {
                "status": "completed",
                "narrative": "Factory 目前只保留 14 个阶段空壳，内部生产实现已全部清空，等待重写。",
                "generated": [],
                "warnings": ["当前没有真实的生产实现。"],
                "next_steps": [
                    "按阶段逐个重写内部逻辑。",
                    "底层统一使用 LangGraph / LangChain 体系。",
                ],
            }
            payload["production_summary"] = state.production_summary
            message = "14 阶段空壳已跑通，但内部实现为空。"

        event = FactoryEvent(
            run_id=state.run_id,
            stage=stage,
            status=event_status,
            title=title,
            message=message,
            payload=payload,
        )
        return self._with_event(state, node=stage, event=event)

    def _with_event(
        self,
        state: FactoryProductionState,
        *,
        node: str,
        event: FactoryEvent,
    ) -> FactoryProductionStateDict:
        state.current_stage = event.stage
        state.graph_node = node
        state.stage_history.append(event.stage)
        state.events.append(event)
        try:
            self.context.trace_store.append_event(event)
        except Exception:
            pass
        return state.as_graph_state()


def _next_stage(stage: str) -> str | None:
    try:
        index = FACTORY_STAGE_SEQUENCE.index(stage)
    except ValueError:
        return None
    if index >= len(FACTORY_STAGE_SEQUENCE) - 1:
        return None
    return FACTORY_STAGE_SEQUENCE[index + 1]
