from __future__ import annotations

import unittest
from unittest.mock import patch

from agent_factory.factory_package.schemas import RequirementClarityOutput, RequirementFrame, RequirementMergeOutput
from agent_factory.factory_package.stage_subgraphs.requirement_clarification import (
    run_requirement_capture_subgraph,
)


class RequirementCaptureSubgraphTest(unittest.TestCase):
    def test_clear_requirement_finalizes_requirement_brief(self) -> None:
        frame = RequirementFrame(
            goal="生成一个本地可运行的文件整理 Agent",
            primary_scenarios=["整理项目目录中的重复文件"],
            behavior_mode="CLI-first LangGraph agent",
            action_boundary="只在用户授权后执行写入操作",
            output_expectation="给出整理计划和执行结果",
        )
        with patch(
            "agent_factory.factory_package.stage_subgraphs.requirement_clarification.call_structured_model",
            side_effect=[
                RequirementMergeOutput(current_requirement=frame.goal, requirement_frame=frame),
                RequirementClarityOutput(is_clear=True, confidence=0.92, reason="目标和边界已足够明确"),
            ],
        ):
            result = run_requirement_capture_subgraph(
                {
                    "requirement": "生成一个本地可运行的文件整理 Agent",
                    "status": "running",
                    "stage_log": [],
                    "errors": [],
                }
            )

        self.assertEqual(result["current_stage"], "requirement_capture")
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["requirement_brief"]["status"], "captured")
        self.assertEqual(result["requirement_brief"]["requirement_frame"]["goal"], frame.goal)
        self.assertEqual(result["stage_log"][0]["stage_id"], "requirement_capture")

    def test_unclear_requirement_stops_with_human_review_when_iteration_limit_reached(self) -> None:
        frame = RequirementFrame(goal="做一个 Agent")
        with patch(
            "agent_factory.factory_package.stage_subgraphs.requirement_clarification.call_structured_model",
            side_effect=[
                RequirementMergeOutput(current_requirement=frame.goal, requirement_frame=frame),
                RequirementClarityOutput(
                    is_clear=False,
                    confidence=0.3,
                    reason="缺少业务目标和资源边界",
                    missing_fields=["业务目标", "资源边界"],
                ),
            ],
        ):
            result = run_requirement_capture_subgraph(
                {
                    "requirement": "做一个 Agent",
                    "status": "running",
                    "stage_log": [],
                    "errors": [],
                    "requirement_capture": {"iteration_count": 5},
                }
            )

        self.assertEqual(result["requirement_brief"]["status"], "needs_human_review")
        self.assertEqual(result["graph_control"]["action"], "end")
        self.assertEqual(result["requirement_brief"]["clarity"]["missing_decisions"], ["业务目标", "资源边界"])


if __name__ == "__main__":
    unittest.main()
