from __future__ import annotations

from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from agent_factory.factory_graph.graph import build_factory_graph
from agent_factory.models import reset_chat_models
from agent_factory.prompts import CaptureIntentOutput


MODEL_ENV = {
    "AGENTFACTORY_OPENAI_MODEL": "",
    "AGENTFACTORY_OPENAI_API_KEY": "",
    "AGENTFACTORY_OPENAI_BASE_URL": "",
    "AGENTFACTORY_TASK_MODEL": "",
    "AGENTFACTORY_LLM_TEMPERATURE": "",
    "AGENTFACTORY_LLM_MAX_OUTPUT_TOKENS": "",
    "AGENTFACTORY_LLM_TIMEOUT_SECONDS": "",
    "AGENTFACTORY_TASK_TEMPERATURE": "",
    "AGENTFACTORY_TASK_MAX_OUTPUT_TOKENS": "",
}


class CaptureRequirementSubgraphTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_models()

    def tearDown(self) -> None:
        reset_chat_models()

    def test_inspect_factory_request_ends_after_capture_requirement(self) -> None:
        app = build_factory_graph()
        with patch.dict(os.environ, MODEL_ENV):
            result = app.invoke(
                {
                    "requirement": "你现在有什么工具可以使用",
                    "messages": [HumanMessage(content="你现在有什么工具可以使用")],
                    "status": "running",
                    "stage_log": [],
                    "errors": [],
                }
            )

        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["current_stage"], "capture_requirement")
        self.assertEqual(result["capture_intent"]["intent"], "inspect_factory")
        self.assertEqual(len(result["stage_log"]), 1)
        self.assertIn("file_read", result["messages"][-1].content)
        self.assertIsInstance(result["messages"][-1], AIMessage)

    def test_manufacture_request_continues_through_factory_stages(self) -> None:
        app = build_factory_graph()
        with patch.dict(os.environ, MODEL_ENV):
            result = app.invoke(
                {
                    "requirement": "创建一个记账 Agent",
                    "messages": [HumanMessage(content="创建一个记账 Agent")],
                    "status": "running",
                    "stage_log": [],
                    "errors": [],
                }
            )

        self.assertEqual(result["status"], "completed_skeleton")
        self.assertEqual(result["current_stage"], "complete_summary")
        self.assertEqual(result["capture_intent"]["intent"], "manufacture_agent")
        self.assertEqual(len(result["stage_log"]), 14)
        self.assertEqual(result["requirement_brief"]["capture_route"], "manufacture_agent")

    def test_explicit_run_flag_forces_manufacture_route(self) -> None:
        app = build_factory_graph(stop_after_stage="capture_requirement")
        with patch.dict(os.environ, MODEL_ENV):
            result = app.invoke(
                {
                    "requirement": "投资研究",
                    "force_manufacture": True,
                    "messages": [HumanMessage(content="投资研究")],
                    "status": "running",
                    "stage_log": [],
                    "errors": [],
                }
            )

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["current_stage"], "capture_requirement")
        self.assertEqual(result["capture_intent"]["intent"], "manufacture_agent")
        self.assertEqual(result["capture_intent"]["router"], "shell_mode")

    def test_create_agent_mode_bypasses_intent_routing(self) -> None:
        app = build_factory_graph(stop_after_stage="capture_requirement")
        with patch.dict(os.environ, MODEL_ENV):
            result = app.invoke(
                {
                    "requirement": "你好",
                    "interaction_mode": "create_agent",
                    "messages": [HumanMessage(content="你好")],
                    "status": "running",
                    "stage_log": [],
                    "errors": [],
                }
            )

        self.assertEqual(result["status"], "running")
        self.assertEqual(result["current_stage"], "capture_requirement")
        self.assertEqual(result["capture_intent"]["intent"], "manufacture_agent")
        self.assertEqual(result["capture_intent"]["router"], "shell_mode")

    def test_task_model_intent_result_is_used_before_rules(self) -> None:
        class FakeStructuredModel:
            def bind(self, **kwargs):
                self.bound_kwargs = kwargs
                return self

            def with_config(self, **kwargs):
                self.config_kwargs = kwargs
                return self

            def invoke(self, prompt_value):
                joined = "\n".join(message.content for message in prompt_value.to_messages())
                self.prompt_text = joined
                return CaptureIntentOutput(
                    intent="inspect_factory",
                    confidence=0.96,
                    reason="用户询问工厂能力",
                    reply_hint="show_tools",
                    should_run_graph=False,
                )

        class FakeTaskModel:
            def __init__(self) -> None:
                self.structured = FakeStructuredModel()

            def with_structured_output(self, schema, *, method):
                self.schema = schema
                self.method = method
                return self.structured

        fake_task_model = FakeTaskModel()
        fake_task_settings = SimpleNamespace(model="task-small", max_tokens=256)
        app = build_factory_graph()
        with (
            patch(
                "agent_factory.factory_graph.stage_subgraphs.capture_requirement.get_task_model",
                return_value=fake_task_model,
            ),
            patch(
                "agent_factory.factory_graph.stage_subgraphs.capture_requirement.get_task_model_settings",
                return_value=fake_task_settings,
            ),
        ):
            result = app.invoke(
                {
                    "requirement": "介绍一下",
                    "messages": [HumanMessage(content="介绍一下")],
                    "status": "running",
                    "stage_log": [],
                    "errors": [],
                }
            )

        self.assertEqual(result["capture_intent"]["intent"], "inspect_factory")
        self.assertEqual(result["capture_intent"]["router"], "task_model:task-small")
        self.assertFalse(result["capture_intent"]["fallback_used"])
        self.assertEqual(result["graph_control"]["action"], "end")
        self.assertIs(fake_task_model.schema, CaptureIntentOutput)
        self.assertEqual(fake_task_model.method, "json_mode")
        self.assertEqual(fake_task_model.structured.bound_kwargs, {"max_tokens": 256})
        self.assertEqual(fake_task_model.structured.config_kwargs, {"tags": ["nostream"]})
        self.assertIn("Output JSON schema", fake_task_model.structured.prompt_text)

    def test_no_manufacture_intent_ends_as_unclear_without_chatting(self) -> None:
        app = build_factory_graph()
        with patch.dict(os.environ, MODEL_ENV):
            result = app.invoke(
                {
                    "requirement": "今天天气不错",
                    "messages": [HumanMessage(content="今天天气不错")],
                    "status": "running",
                    "stage_log": [],
                    "errors": [],
                }
            )

        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["current_stage"], "capture_requirement")
        self.assertEqual(result["capture_intent"]["intent"], "chat")
        self.assertEqual(result["graph_control"]["action"], "end")
        self.assertEqual(len(result["stage_log"]), 1)
        self.assertIn("不确定当前输入应进入哪个执行路径", result["messages"][-1].content)


if __name__ == "__main__":
    unittest.main()
