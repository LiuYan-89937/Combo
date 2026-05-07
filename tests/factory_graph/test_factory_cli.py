from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from typer.testing import CliRunner

from agent_factory.cli import app
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


class FactoryCliTest(unittest.TestCase):
    def setUp(self) -> None:
        reset_chat_models()

    def tearDown(self) -> None:
        reset_chat_models()

    def test_create_agent_prints_graph_details(self) -> None:
        runner = CliRunner()
        with patch.dict(os.environ, MODEL_ENV):
            result = runner.invoke(
                app,
                [
                    "create-agent",
                    "--prompt",
                    "创建一个记账 Agent",
                    "--stop-after-stage",
                    "capture_requirement",
                ],
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Factory Run Started", result.output)
        self.assertIn("Node: capture_requirement", result.output)
        self.assertIn("capture subgraph routed input to manufacture_agent", result.output)
        self.assertIn("Factory Run Completed", result.output)

    def test_test_stages_runs_whole_skeleton(self) -> None:
        runner = CliRunner()
        with patch.dict(os.environ, MODEL_ENV):
            result = runner.invoke(app, ["test-stages", "--prompt", "创建一个记账 Agent"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("stage skeleton test completed", result.output)
        self.assertIn("stage_log_count: 14", result.output)

    def test_natural_language_tool_question_does_not_run_all_stages(self) -> None:
        runner = CliRunner()
        with patch.dict(os.environ, MODEL_ENV):
            result = runner.invoke(app, ["create-agent", "--prompt", "你现在有什么工具可以使用"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("file_read", result.output)
        self.assertIn("search_text", result.output)
        self.assertIn("stage_log_count", result.output)
        self.assertNotIn("Node: understand_requirement", result.output)

    def test_natural_language_chat_does_not_enter_manufacture_stages(self) -> None:
        runner = CliRunner()
        with patch.dict(os.environ, MODEL_ENV):
            result = runner.invoke(app, ["create-agent", "--prompt", "今天天气不错"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("capture subgraph answered a chat request", result.output)
        self.assertIn("今天天气不错", result.output)
        self.assertNotIn("Node: understand_requirement", result.output)


if __name__ == "__main__":
    unittest.main()
