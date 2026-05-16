from __future__ import annotations

import inspect
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from langchain_core.exceptions import OutputParserException

from agent_factory.factory_graph.model_call import (
    FactoryModelCallError,
    STRUCTURED_OUTPUT_MAX_ATTEMPTS,
    call_structured_model,
)
from agent_factory.factory_graph.schemas import RequirementClarityOutput
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
                output_model=RequirementClarityOutput,
                values={},
            )

    def test_structured_model_repairs_schema_failures_with_bounded_react_loop(self) -> None:
        class FakeStructuredModel:
            def __init__(self) -> None:
                self.invocations: list[list[object]] = []

            def with_config(self, **kwargs):
                return self

            def bind(self, **kwargs):
                return self

            def invoke(self, messages):
                self.invocations.append(list(messages))
                if len(self.invocations) < 3:
                    raise OutputParserException("missing_fields has too many items")
                return RequirementClarityOutput(
                    is_clear=False,
                    confidence=0.9,
                    reason="需求仍需澄清。",
                    missing_fields=["目标", "场景"],
                )

        class FakeModel:
            def __init__(self) -> None:
                self.structured = FakeStructuredModel()

            def with_structured_output(self, schema, *, method):
                self.schema = schema
                self.method = method
                return self.structured

        fake_model = FakeModel()
        with (
            patch("agent_factory.factory_graph.model_call.get_main_model", return_value=fake_model),
            patch(
                "agent_factory.factory_graph.model_call.get_main_model_settings",
                return_value=SimpleNamespace(max_tokens=None),
            ),
        ):
            result = call_structured_model(
                stage_id="requirement_capture",
                prompt_id=PromptId.REQUIREMENT_CAPTURE_CLARITY,
                output_model=RequirementClarityOutput,
                values={
                    "original_input": "本地 mysql 管理",
                    "current_requirement": "本地 mysql 管理",
                    "requirement_frame": "{}",
                    "runtime_environment": "cli factory",
                    "output_json_schema": "{}",
                },
            )

        self.assertIsInstance(result, RequirementClarityOutput)
        self.assertEqual(fake_model.method, "json_mode")
        self.assertEqual(len(fake_model.structured.invocations), 3)
        self.assertIn("failed schema validation", fake_model.structured.invocations[1][-1].content)

    def test_structured_model_stops_after_max_repair_attempts(self) -> None:
        class AlwaysFailStructuredModel:
            def __init__(self) -> None:
                self.invocation_count = 0

            def with_config(self, **kwargs):
                return self

            def bind(self, **kwargs):
                return self

            def invoke(self, messages):
                self.invocation_count += 1
                raise OutputParserException("schema still invalid")

        class FakeModel:
            def __init__(self) -> None:
                self.structured = AlwaysFailStructuredModel()

            def with_structured_output(self, schema, *, method):
                return self.structured

        fake_model = FakeModel()
        with (
            patch("agent_factory.factory_graph.model_call.get_main_model", return_value=fake_model),
            patch(
                "agent_factory.factory_graph.model_call.get_main_model_settings",
                return_value=SimpleNamespace(max_tokens=None),
            ),
            self.assertRaisesRegex(FactoryModelCallError, "schema still invalid"),
        ):
            call_structured_model(
                stage_id="requirement_capture",
                prompt_id=PromptId.REQUIREMENT_CAPTURE_CLARITY,
                output_model=RequirementClarityOutput,
                values={
                    "original_input": "本地 mysql 管理",
                    "current_requirement": "本地 mysql 管理",
                    "requirement_frame": "{}",
                    "runtime_environment": "cli factory",
                    "output_json_schema": "{}",
                },
            )

        self.assertEqual(fake_model.structured.invocation_count, STRUCTURED_OUTPUT_MAX_ATTEMPTS)

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

if __name__ == "__main__":
    unittest.main()
