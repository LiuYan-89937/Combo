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

    def test_chat_graph_runs_react_tool_observation_loop(self) -> None:
        class FakeTaskModel:
            def __init__(self) -> None:
                self.calls = 0

            def bind_tools(self, tools):
                self.bound_tools = tools
                return self

            def bind(self, **kwargs):
                self.bound_kwargs = kwargs
                return self

            def invoke(self, prompt_value):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "file_list",
                                "args": {"path": ".", "recursive": False, "max_entries": 10},
                                "id": "call_file_list",
                            }
                        ],
                    )
                self.second_prompt_messages = prompt_value.to_messages()
                observations = [
                    message for message in self.second_prompt_messages if isinstance(message, ToolMessage)
                ]
                return AIMessage(content=f"基于 {len(observations)} 个 Observation 回答。")

        fake_task_model = FakeTaskModel()
        app = build_factory_chat_graph()
        with (
            patch.dict(os.environ, MODEL_ENV),
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

        self.assertEqual(fake_task_model.calls, 2)
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["messages"][-1].content, "基于 1 个 Observation 回答。")
        self.assertTrue(any(isinstance(message, ToolMessage) for message in result["messages"]))
        self.assertIn("file_list", {tool.name for tool in fake_task_model.bound_tools})

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
