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

    def test_shell_chat_mode_does_not_run_manufacture_stages(self) -> None:
        runner = CliRunner()
        with patch.dict(os.environ, MODEL_ENV):
            result = runner.invoke(app, ["shell"], input="/chat\n今天天气不错\n/exit\n/quit\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("enter chat mode", result.output)
        self.assertIn("Factory Chat Started", result.output)
        self.assertIn("Factory Chat Completed", result.output)
        self.assertNotIn("Node: capture_requirement", result.output)
        self.assertNotIn("Node: understand_requirement", result.output)

    def test_shell_create_agent_mode_runs_manufacture_stages(self) -> None:
        runner = CliRunner()
        with patch.dict(os.environ, MODEL_ENV):
            result = runner.invoke(app, ["shell"], input="/create-agent\n你好\n/exit\n/quit\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("enter create_agent mode", result.output)
        self.assertIn("capture subgraph routed input to manufacture_agent", result.output)
        self.assertIn("Node: understand_requirement", result.output)

    def test_shell_requires_mode_before_natural_language_input(self) -> None:
        runner = CliRunner()
        with patch.dict(os.environ, MODEL_ENV):
            result = runner.invoke(app, ["shell"], input="你好\n/quit\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("先输入 /chat 或 /create-agent 进入模式。", result.output)
        self.assertNotIn("Factory Run Started", result.output)


if __name__ == "__main__":
    unittest.main()
