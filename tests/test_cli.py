from __future__ import annotations

import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from agent_factory.cli.main import app
from agent_factory.cli.rendering import render_banner
from agent_factory.cli.session import ShellSession
from agent_factory.cli.slash import SlashCommandDispatcher


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_cli_help_lists_core_commands(self) -> None:
        result = self.runner.invoke(app, ["--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("validate-agent", result.output)
        self.assertIn("create-agent", result.output)
        self.assertIn("shell", result.output)

    def test_validate_agent_success(self) -> None:
        result = self.runner.invoke(app, ["validate-agent", "examples/customer_service_agent"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Status", result.output)
        self.assertIn("passed", result.output)

    def test_validate_agent_json_is_machine_readable(self) -> None:
        result = self.runner.invoke(
            app,
            ["validate-agent", "examples/customer_service_agent", "--json"],
        )

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["issues"], [])
        self.assertTrue(payload["root_path"].endswith("examples/customer_service_agent"))
        self.assertNotIn("No-89937", result.output)
        self.assertNotIn("AgentPackage validation", result.output)

    def test_validate_agent_failure_exits_non_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "instructions.yaml").write_text("kind: InstructionSpec\n", encoding="utf-8")

            result = self.runner.invoke(app, ["validate-agent", str(root), "--json"])

        self.assertEqual(result.exit_code, 1, result.output)
        payload = json.loads(result.output)
        self.assertGreater(len(payload["issues"]), 0)
        self.assertIn("missing_required_file", {issue["code"] for issue in payload["issues"]})

    def test_init_factory_creates_workspace(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(app, ["init", "--json"])

            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertTrue(payload["workspace_path"].endswith(".agentfactory"))
            self.assertTrue(Path(payload["config_path"]).exists())

    def test_create_agent_json_reports_missing_model_config_without_rich_output(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(
                app,
                ["create-agent", "--prompt", "创建一个客服 Agent", "--draft", "--json", "--no-stream"],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertFalse(payload["implemented"])
            self.assertEqual(payload["error"]["code"], "model_config_error")
            self.assertTrue(Path(payload["trace_path"]).exists())
            self.assertTrue(Path(payload["memory_path"]).exists())
            self.assertNotIn("No-89937", result.output)

    def test_create_agent_json_stream_outputs_jsonl(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(
                app,
                ["create-agent", "--prompt", "创建一个客服 Agent", "--draft", "--json", "--stream"],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            lines = [line for line in result.output.splitlines() if line.strip()]
            self.assertGreaterEqual(len(lines), 2)
            payloads = [json.loads(line) for line in lines]
            self.assertEqual(payloads[0]["stage"], "capture_requirement")
            self.assertEqual(payloads[-1]["stage"], "failed")
            self.assertNotIn("No-89937", result.output)

    def test_create_agent_human_output_uses_factory_block(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(
                app,
                ["create-agent", "--prompt", "创建一个客服 Agent", "--draft"],
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Factory", result.output)
            self.assertIn("Requirement captured", result.output)
            self.assertIn("model configuration is missing", result.output)

    def test_shell_startup_shows_ascii_banner(self) -> None:
        result = self.runner.invoke(app, ["shell"], input="/exit\n")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue("AgentFactory" in result.output or "AgentFactory v0.1" in result.output)

    def test_shell_help_uses_grouped_slash_commands(self) -> None:
        result = self.runner.invoke(app, ["shell"], input="/help\n/exit\n")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Slash commands", result.output)
        self.assertIn("/create-agent", result.output)
        self.assertIn("/apply-patch-plan", result.output)
        self.assertIn("Session", result.output)

    def test_shell_create_agent_streams_events(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(
                app,
                ["shell"],
                input="创建一个客服 Agent\n/create-agent --draft\n/exit\n",
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Requirement captured", result.output)
            self.assertIn("Factory context loaded", result.output)
            self.assertIn("Factory production failed", result.output)

    def test_banner_falls_back_on_narrow_terminal(self) -> None:
        output = StringIO()
        console = Console(file=output, width=60, force_terminal=False)

        render_banner(console, workspace=".", state="test")

        rendered = output.getvalue()
        self.assertIn("AgentFactory v0.1", rendered)
        self.assertNotIn(",---.-,", rendered)


class SlashShellTests(unittest.TestCase):
    def test_shell_session_captures_pending_requirement(self) -> None:
        session = ShellSession()
        dispatcher = SlashCommandDispatcher(session=session)

        result = dispatcher.dispatch("创建一个客服 Agent")

        self.assertEqual(result.kind, "requirement")
        self.assertEqual(session.pending_requirement, "创建一个客服 Agent")

    def test_slash_help_includes_session_state(self) -> None:
        session = ShellSession(pending_requirement="创建一个客服 Agent")
        dispatcher = SlashCommandDispatcher(session=session)

        result = dispatcher.dispatch("/help")

        self.assertEqual(result.kind, "help")
        self.assertIn("/create-agent", result.message or "")
        self.assertIn("创建一个客服 Agent", result.message or "")

    def test_slash_validate_reuses_validate_service(self) -> None:
        dispatcher = SlashCommandDispatcher()

        result = dispatcher.dispatch("/validate examples/customer_service_agent")

        self.assertEqual(result.kind, "validate_agent")
        self.assertIsNotNone(result.validation_report)
        self.assertTrue(result.validation_report.ok)

    def test_slash_create_agent_uses_pending_requirement(self) -> None:
        session = ShellSession(pending_requirement="创建一个客服 Agent")
        dispatcher = SlashCommandDispatcher(session=session)

        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path.cwd()
            os.chdir(tmpdir)
            try:
                result = dispatcher.dispatch("/create-agent --draft")
                self.assertEqual(result.kind, "create_agent")
                self.assertIsNotNone(result.create_result)
                self.assertFalse(result.create_result.implemented)
                self.assertTrue(result.create_result.memory_path.exists())
            finally:
                os.chdir(cwd)

    def test_slash_exit_requests_exit(self) -> None:
        result = SlashCommandDispatcher().dispatch("/exit")

        self.assertEqual(result.kind, "exit")
        self.assertTrue(result.exit_requested)


if __name__ == "__main__":
    unittest.main()
