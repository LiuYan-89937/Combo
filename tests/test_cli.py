from __future__ import annotations

import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from agent_factory.application import (
    CreateAgentRequest,
    CreateAgentResult,
    CreateAgentService,
    RunAgentService,
)
from agent_factory.cli.completion import ContextualSlashCompleter
from agent_factory.cli.main import app
from agent_factory.cli.rendering import render_banner
from agent_factory.cli.session import ShellSession
from agent_factory.cli.shell import _collect_requirement_lines, _should_stream_create_agent
from agent_factory.cli.slash import SlashCommandDispatcher
from tests.test_factory_agent import service_with_responses, valid_primitives_payload


def _generated_package(start_path: Path) -> Path:
    service = CreateAgentService(model_service=service_with_responses([valid_primitives_payload()]))
    result = service.create_agent(
        CreateAgentRequest(prompt="创建客服 Agent", start_path=start_path, stream=False)
    )
    assert result.output_path is not None
    return result.output_path


class RecordingCreateAgentService:
    def __init__(self) -> None:
        self.requests: list[CreateAgentRequest] = []

    def create_agent(self, request: CreateAgentRequest) -> CreateAgentResult:
        self.requests.append(request)
        root = Path.cwd() / ".agentfactory"
        return CreateAgentResult(
            run_id="test-run",
            requirement=request.prompt,
            status="completed",
            implemented=True,
            workspace_path=root,
            trace_path=root / "traces" / "factory_runs.jsonl",
            memory_path=root / "memory" / "factory_memory.jsonl",
        )


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

    def test_test_agent_json_reads_generated_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))

            result = self.runner.invoke(app, ["test-agent", str(package_path), "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["verification_report"]["status"], "passed")
        self.assertGreaterEqual(payload["scenario_count"], 1)
        self.assertNotIn("Local verification", result.output)

    def test_test_agent_missing_reports_exits_non_zero(self) -> None:
        result = self.runner.invoke(app, ["test-agent", "examples/customer_service_agent", "--json"])

        self.assertEqual(result.exit_code, 1, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("factory_verification_report_missing", {issue["code"] for issue in payload["issues"]})

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

    def test_drafts_list_and_show_generated_agent(self) -> None:
        with self.runner.isolated_filesystem():
            package_path = _generated_package(Path.cwd())

            list_result = self.runner.invoke(app, ["drafts", "list", "--json"])
            self.assertEqual(list_result.exit_code, 0, list_result.output)
            payload = json.loads(list_result.output)
            self.assertEqual(len(payload["drafts"]), 1)
            self.assertEqual(Path(payload["drafts"][0]["path"]), package_path)

            show_result = self.runner.invoke(app, ["drafts", "show", "latest", "--json"])
            self.assertEqual(show_result.exit_code, 0, show_result.output)
            detail = json.loads(show_result.output)
            self.assertEqual(detail["summary"]["validation_status"], "passed")
            self.assertIn("persona", detail)

    def test_drafts_run_uses_generated_package(self) -> None:
        with self.runner.isolated_filesystem():
            _generated_package(Path.cwd())

            result = self.runner.invoke(
                app,
                ["drafts", "run", "latest", "--input", "帮我查订单 123", "--json"],
                env={"AGENTFACTORY_LLM_PROVIDER": "fake"},
            )

            self.assertEqual(result.exit_code, 0, result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload["result"]["status"], "completed")
            self.assertIsNotNone(payload["package_path"])

    def test_drafts_delete_requires_confirmation_and_deletes(self) -> None:
        with self.runner.isolated_filesystem():
            package_path = _generated_package(Path.cwd())

            blocked = self.runner.invoke(app, ["drafts", "delete", "latest", "--json"])
            self.assertEqual(blocked.exit_code, 1, blocked.output)
            blocked_payload = json.loads(blocked.output)
            self.assertFalse(blocked_payload["deleted"])
            self.assertTrue(package_path.exists())

            deleted = self.runner.invoke(app, ["drafts", "delete", "latest", "--yes", "--json"])
            self.assertEqual(deleted.exit_code, 0, deleted.output)
            deleted_payload = json.loads(deleted.output)
            self.assertTrue(deleted_payload["deleted"])
            self.assertFalse(package_path.exists())

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

    def test_requirement_box_submits_on_enter(self) -> None:
        requirement = _collect_requirement_lines(
            lambda: "创建一个本地 SQLite 数据库管理 Agent，SQL 注入输入比如 \"'; DROP TABLE customer_tickets; --\" 不得破坏表。"
        )

        self.assertIsNotNone(requirement)
        self.assertIn("SQLite 数据库管理 Agent", requirement or "")
        self.assertIn("DROP TABLE customer_tickets", requirement or "")

    def test_requirement_box_cancel_marker_cancels(self) -> None:
        self.assertIsNone(_collect_requirement_lines(lambda: "/cancel"))

    def test_shell_create_agent_streams_by_default(self) -> None:
        self.assertTrue(_should_stream_create_agent("/create-agent"))
        self.assertTrue(_should_stream_create_agent("/create-agent --draft"))
        self.assertFalse(_should_stream_create_agent("/create-agent --no-stream"))

    def test_shell_session_strips_requirement_box_markers(self) -> None:
        session = ShellSession()

        session.capture_requirement("创建 Agent\n/done")

        self.assertEqual(session.pending_requirement, "创建 Agent")

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

    def test_slash_test_reuses_test_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            dispatcher = SlashCommandDispatcher()

            result = dispatcher.dispatch(f"/test {package_path}")

        self.assertEqual(result.kind, "test_agent")
        self.assertIsNotNone(result.test_result)
        self.assertTrue(result.test_result.ok)

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

    def test_slash_create_agent_accepts_multiline_prompt_with_inner_quotes(self) -> None:
        service = RecordingCreateAgentService()
        dispatcher = SlashCommandDispatcher(create_service=service)
        prompt = (
            '/create-agent --prompt "创建一个本地 SQLite 数据库管理 Agent，名字叫 LocalDBManager。\n'
            "测试要求：\n"
            "- SQL 注入输入比如 \"'; DROP TABLE customer_tickets; --\" 不得破坏表。\n"
            '输出风格：简洁明确。" --draft'
        )

        result = dispatcher.dispatch(prompt)

        self.assertEqual(result.kind, "create_agent")
        self.assertEqual(len(service.requests), 1)
        self.assertTrue(service.requests[0].draft)
        self.assertIn("LocalDBManager", service.requests[0].prompt)
        self.assertIn("DROP TABLE customer_tickets", service.requests[0].prompt)
        self.assertNotIn("--draft", service.requests[0].prompt)

    def test_slash_create_agent_accepts_unclosed_prompt_quote(self) -> None:
        service = RecordingCreateAgentService()
        dispatcher = SlashCommandDispatcher(create_service=service)

        result = dispatcher.dispatch('/create-agent --prompt "生成一个虚拟恋爱女友小美 --draft')

        self.assertEqual(result.kind, "create_agent")
        self.assertEqual(service.requests[0].prompt, "生成一个虚拟恋爱女友小美")
        self.assertTrue(service.requests[0].draft)

    def test_slash_drafts_use_selects_agent_for_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_path = _generated_package(root)
            cwd = Path.cwd()
            os.chdir(root)
            try:
                session = ShellSession()
                dispatcher = SlashCommandDispatcher(
                    session=session,
                    run_service=RunAgentService(model_service=service_with_responses([""])),
                )

                use_result = dispatcher.dispatch("/drafts use latest")
                self.assertEqual(use_result.kind, "drafts")
                self.assertEqual(session.selected_agent_path, package_path)

                run_result = dispatcher.dispatch('/run --input "你好"')
                self.assertEqual(run_result.kind, "run_agent")
                self.assertTrue(run_result.run_result.ok)
            finally:
                os.chdir(cwd)

    def test_slash_run_without_path_defaults_to_latest_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_path = _generated_package(root)
            cwd = Path.cwd()
            os.chdir(root)
            try:
                dispatcher = SlashCommandDispatcher(
                    run_service=RunAgentService(model_service=service_with_responses([""])),
                )

                result = dispatcher.dispatch('/run --input "你好"')

                self.assertEqual(result.kind, "run_agent")
                self.assertTrue(result.run_result.ok)
                self.assertEqual(result.run_result.package_path, package_path)
            finally:
                os.chdir(cwd)

    def test_slash_drafts_delete_requires_yes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_path = _generated_package(root)
            cwd = Path.cwd()
            os.chdir(root)
            try:
                dispatcher = SlashCommandDispatcher()

                blocked = dispatcher.dispatch("/drafts delete latest")
                self.assertEqual(blocked.kind, "registry")
                self.assertIn("--yes", blocked.message or "")
                self.assertTrue(package_path.exists())

                deleted = dispatcher.dispatch("/drafts delete latest --yes")
                self.assertEqual(deleted.kind, "registry")
                self.assertIn("Deleted draft", deleted.message or "")
                self.assertFalse(package_path.exists())
            finally:
                os.chdir(cwd)

    def test_contextual_completion_after_drafts_does_not_show_top_level_commands(self) -> None:
        from prompt_toolkit.document import Document

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _generated_package(root)
            cwd = Path.cwd()
            os.chdir(root)
            try:
                dispatcher = SlashCommandDispatcher()
                completer = ContextualSlashCompleter(
                    session=dispatcher.session,
                    drafts_service=dispatcher.drafts_service,
                )

                completions = list(completer.get_completions(Document("/drafts /"), None))
                texts = [completion.text for completion in completions]

                self.assertIn("list", texts)
                self.assertIn("latest", texts)
                self.assertIn("agent", texts)
                self.assertNotIn("/run", texts)
                self.assertNotIn("/create-agent", texts)
            finally:
                os.chdir(cwd)

    def test_slash_exit_requests_exit(self) -> None:
        result = SlashCommandDispatcher().dispatch("/exit")

        self.assertEqual(result.kind, "exit")
        self.assertTrue(result.exit_requested)


if __name__ == "__main__":
    unittest.main()
