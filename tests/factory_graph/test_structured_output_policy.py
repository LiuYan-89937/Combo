from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from agent_factory.factory_graph.model_call import FactoryModelCallError, call_structured_model
from agent_factory.factory_graph.schemas import ResourceReactDecision
from agent_factory.factory_graph.stage_subgraphs import resource_preparation
from agent_factory.factory_graph.stages import (
    graph_behavior_planning,
    node_strategy_planning,
    tool_capability_planning,
)
from agent_factory.prompts import PromptId


class StructuredOutputPolicyTest(unittest.TestCase):
    def test_structured_model_calls_require_output_schema(self) -> None:
        with self.assertRaisesRegex(FactoryModelCallError, "output_json_schema"):
            call_structured_model(
                stage_id="runtime_pattern_selection",
                prompt_id=PromptId.RUNTIME_PATTERN_SELECTION,
                output_model=ResourceReactDecision,
                values={},
            )

    def test_structured_stage_modules_do_not_hand_write_langchain_structured_calls(self) -> None:
        modules = [
            graph_behavior_planning,
            node_strategy_planning,
            tool_capability_planning,
        ]
        for module in modules:
            source = inspect.getsource(module)
            self.assertNotIn("with_structured_output", source)
            self.assertIn("call_structured_model", source)

    def test_resource_react_final_output_uses_structured_normalizer(self) -> None:
        decision = ResourceReactDecision(
            action="needs_user_input",
            requirements=[],
            check_results_summary=[],
            missing_requirements=["resource_x"],
            user_prompt="请补充 resource_x。",
            resource_draft={},
            validation_notes=[],
        )

        with patch(
            "agent_factory.factory_graph.stage_subgraphs.resource_preparation.call_structured_model",
            return_value=decision,
        ) as structured_call:
            patch_result = resource_preparation._parse_resource_react_output(
                {
                    "messages": [
                        AIMessage(
                            content=(
                                "这里是自然语言说明。\n"
                                "```json\n"
                                "{\"action\":\"needs_user_input\"}\n"
                                "```\n"
                                "后面还有多余文本。"
                            )
                        )
                    ],
                    "resource_condition_plan": {
                        "status": "collecting",
                        "requirements": [],
                        "check_results": [],
                        "user_inputs": [],
                        "resource_draft": {},
                    },
                    "tool_capability_plan": {},
                }
            )

        self.assertEqual(patch_result["resource_condition_plan"]["status"], "needs_input")
        self.assertEqual(
            patch_result["resource_condition_plan"]["react_decision"]["missing_requirements"],
            ["resource_x"],
        )
        self.assertEqual(structured_call.call_args.kwargs["prompt_id"], PromptId.RESOURCE_REACT_DECISION)
        self.assertIs(structured_call.call_args.kwargs["output_model"], ResourceReactDecision)


if __name__ == "__main__":
    unittest.main()
