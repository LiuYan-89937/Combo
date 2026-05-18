from __future__ import annotations

from types import SimpleNamespace
import os
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_factory.factory_graph.chat_graph import build_factory_chat_graph
from agent_factory.models import reset_chat_models


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


class FactoryChatGraphTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_models()

    def tearDown(self) -> None:
        reset_chat_models()

    def test_chat_graph_binds_registered_factory_tools_without_forcing_tool_execution(self) -> None:
        class FakeTaskModel:
            def __init__(self) -> None:
                self.calls = 0
                self.bound_tools = None

            def bind_tools(self, tools):
                self.bound_tools = tools
                return self

            def bind(self, **kwargs):
                self.bound_kwargs = kwargs
                return self

            def invoke(self, prompt_value):
                self.calls += 1
                return AIMessage(content="我可以直接回答。")

        fake_task_model = FakeTaskModel()
        app = build_factory_chat_graph()
        with (
            patch.dict(os.environ, MODEL_ENV),
            patch(
                "agent_factory.factory_graph.chat_graph.prompt_values",
                side_effect=lambda stage_id, values: {
                    "factory_operating_context": "factory",
                    "factory_default_implementation_context": "defaults",
                    "stage_operating_context": stage_id,
                    **values,
                },
            ),
            patch(
                "agent_factory.factory_graph.chat_graph.get_task_model",
                return_value=fake_task_model,
            ),
            patch(
                "agent_factory.factory_graph.chat_graph.get_task_model_settings",
                return_value=SimpleNamespace(model="task-model", max_tokens=128),
            ),
        ):
            result = app.invoke(
                {
                    "messages": [HumanMessage(content="现在工作区有什么文件？")],
                    "status": "running",
                    "errors": [],
                }
            )

        self.assertEqual(fake_task_model.calls, 1)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["messages"][-1].content, "我可以直接回答。")
        self.assertFalse(any(isinstance(message, ToolMessage) for message in result["messages"]))
        self.assertIsNotNone(fake_task_model.bound_tools)
        self.assertTrue(fake_task_model.bound_tools)

    def test_chat_graph_uses_unified_prompt_values_for_memory_injection(self) -> None:
        class FakeTaskModel:
            def bind_tools(self, _tools):
                return self

            def invoke(self, prompt_value):
                text = "\n".join(str(message.content) for message in prompt_value.to_messages())
                return AIMessage(content=f"seen_memory={('cross-session note' in text)}")

        app = build_factory_chat_graph(tools=[])
        with (
            patch.dict(os.environ, MODEL_ENV),
            patch(
                "agent_factory.factory_graph.chat_graph.prompt_values",
                side_effect=lambda stage_id, values: {
                    "factory_operating_context": "factory\ncross-session note",
                    "factory_default_implementation_context": "defaults",
                    "stage_operating_context": stage_id,
                    **values,
                },
            ) as prompt_values_mock,
            patch("agent_factory.factory_graph.chat_graph.get_task_model", return_value=FakeTaskModel()),
            patch(
                "agent_factory.factory_graph.chat_graph.get_task_model_settings",
                return_value=SimpleNamespace(model="task-model", max_tokens=None),
            ),
        ):
            result = app.invoke(
                {
                    "messages": [HumanMessage(content="读取长期记忆了吗？")],
                    "status": "running",
                    "errors": [],
                }
            )

        self.assertTrue(prompt_values_mock.called)
        self.assertEqual(result["messages"][-1].content, "seen_memory=True")

    def test_chat_graph_reports_model_configuration_error(self) -> None:
        app = build_factory_chat_graph()
        with patch.dict(os.environ, MODEL_ENV):
            result = app.invoke(
                {
                    "messages": [HumanMessage(content="你好")],
                    "status": "running",
                    "errors": [],
                }
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"][0]["where"], "chat_model")
        self.assertIn("task model is not configured", result["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
