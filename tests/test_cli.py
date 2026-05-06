from __future__ import annotations

import json
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from rich.console import Console
from typer.testing import CliRunner

from agent_factory.application import (
    CreateAgentRequest,
    CreateAgentResult,
    CreateAgentService,
    RunAgentService,
    RunAgentServiceRequest,
    RunAgentServiceResult,
)
from agent_factory.cli.completion import ContextualSlashCompleter
from agent_factory.cli.main import app
from agent_factory.cli.rendering import FactoryStreamRenderer, render_banner
from agent_factory.cli.rendering import render_create_result, render_event
from agent_factory.cli.rendering import render_factory_stream_result
from agent_factory.cli.session import ShellSession
from agent_factory.cli.shell import (
    _collect_requirement_lines,
    _handle_agent_chat_line,
    _inline_option_label,
    _normalized_question_options,
    _resolve_clarification_answer,
    _should_auto_create_from_text,
    _should_show_thinking,
    _should_stream_create_agent,
    render_slash_result,
)
from agent_factory.cli.slash import SlashCommandDispatcher, SlashCommandResult
from agent_factory.core import EventStatus, FactoryEvent
from agent_factory.isolation import AgentIPCResponse
from agent_factory.runtime import AgentInstanceRuntime, AgentRunResult
from agent_factory.runtime.langchain_chat import ScriptedRuntimeChatModel
from agent_factory.tools import ToolResultEnvelope
from tests.test_factory_agent import service_with_responses, valid_primitives_payload


def _generated_package(start_path: Path) -> Path:
    service = CreateAgentService(model_service=service_with_responses([valid_primitives_payload()]))
    result = service.create_agent(
        CreateAgentRequest(prompt="创建客服 Agent", start_path=start_path, stream=False)
    )
    assert result.output_path is not None
    return result.output_path


def _scripted_runtime() -> AgentInstanceRuntime:
    return AgentInstanceRuntime(chat_model=ScriptedRuntimeChatModel(responses=["ok"]))


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


class RecordingRunAgentService:
    def __init__(self) -> None:
        self.requests = []

    def run_agent(self, request):
        self.requests.append(request)
        return RunAgentServiceResult(
            target=request.target,
            package_path=Path(request.target),
            result=AgentRunResult(
                run_id="approved-run",
                package_path=Path(request.target),
                status="completed",
                answer="approved",
                session_id=request.session_id,
            ),
        )


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()

    def test_cli_help_lists_core_commands(self) -> None:
        result = self.runner.invoke(app, ["--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("agent", result.output)
        self.assertIn("drafts", result.output)
        self.assertIn("registry", result.output)
        self.assertIn("patch", result.output)
        self.assertIn("ops", result.output)
        self.assertIn("shell", result.output)
        self.assertNotIn("validate-agent", result.output)
        self.assertNotIn("create-agent", result.output)

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
        self.assertIn("/repair-agent", result.output)
        self.assertNotIn("/apply-patch-plan", result.output)
        self.assertIn("Session", result.output)

    def test_shell_create_agent_streams_events(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(
                app,
                ["shell"],
                input="创建一个客服 Agent\n/exit\n",
            )

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Requirement captured", result.output)
            self.assertIn("Factory context loaded", result.output)
            self.assertIn("Factory production failed", result.output)

    def test_shell_plain_non_agent_input_gets_guidance_without_create_command(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(app, ["shell"], input="今天吃什么比较好\n/exit\n")

            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("AgentFactory guidance", result.output)
            self.assertNotIn("/create-agent --draft", result.output)

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

    def test_shell_plain_text_auto_creates(self) -> None:
        self.assertTrue(_should_auto_create_from_text("创建一个客服 Agent"))
        self.assertFalse(_should_auto_create_from_text("/create-agent"))
        self.assertFalse(_should_auto_create_from_text("   "))

    def test_shell_create_agent_thinking_toggle(self) -> None:
        self.assertFalse(_should_show_thinking("/create-agent --draft"))
        self.assertTrue(_should_show_thinking("/create-agent --draft --show-thinking"))
        self.assertFalse(_should_show_thinking("/create-agent --show-thinking --hide-thinking"))

    def test_shell_session_strips_requirement_box_markers(self) -> None:
        session = ShellSession()

        session.capture_requirement("创建 Agent\n/done")

        self.assertEqual(session.pending_requirement, "创建 Agent")

    def test_shell_session_appends_clarification_answer(self) -> None:
        session = ShellSession(pending_requirement="创建一个 Agent")
        session.capture_clarification(
            questions=["你想创建哪一类 Agent？"],
            options=[
                {
                    "id": "agent_type",
                    "question": "你想创建哪一类 Agent？",
                    "options": [{"id": "customer_service", "label": "客服 Agent"}],
                }
            ],
        )

        session.capture_requirement("选择客服 Agent，主要用于订单查询。")

        self.assertIn("创建一个 Agent", session.pending_requirement or "")
        self.assertIn("用户补充信息", session.pending_requirement or "")
        self.assertIn("订单查询", session.pending_requirement or "")
        self.assertEqual(session.pending_clarification_questions, [])

    def test_banner_falls_back_on_narrow_terminal(self) -> None:
        output = StringIO()
        console = Console(file=output, width=60, force_terminal=False)

        render_banner(console, workspace=".", state="test")

        rendered = output.getvalue()
        self.assertIn("AgentFactory v0.1", rendered)
        self.assertNotIn(",---.-,", rendered)

    def test_stream_renderer_hides_thinking_by_default(self) -> None:
        event = FactoryEvent(
            run_id="run-1",
            stage="generate_tool_scripts",
            status=EventStatus.PROGRESS,
            title="Generating tool scripts",
            message="Streaming model reasoning and tool code JSON.",
            payload={
                "stream_kind": "node_thinking",
                "thinking": "Reasoning: raw private chain detail",
                "thinking_kind": "reasoning",
                "flow_summary": "Tool 1/2: order_query - calling model for code.",
            },
        )
        output = StringIO()
        console = Console(file=output, width=100, force_terminal=False)

        console.print(FactoryStreamRenderer()._node_panel(event))

        rendered = output.getvalue()
        self.assertIn("Flow", rendered)
        self.assertIn("Tool 1/2: order_query", rendered)
        self.assertIn("--show-thinking", rendered)
        self.assertNotIn("raw private chain detail", rendered)

    def test_stream_renderer_can_show_thinking(self) -> None:
        event = FactoryEvent(
            run_id="run-1",
            stage="analyze_requirement",
            status=EventStatus.PROGRESS,
            title="Analyzing requirement",
            payload={
                "stream_kind": "node_thinking",
                "thinking": "Reasoning: raw model detail",
                "thinking_kind": "reasoning",
                "flow_summary": "Model is reasoning about this node.",
            },
        )
        output = StringIO()
        console = Console(file=output, width=100, force_terminal=False)

        console.print(FactoryStreamRenderer(show_thinking=True)._node_panel(event))

        rendered = output.getvalue()
        self.assertIn("Thinking detail", rendered)
        self.assertIn("raw model detail", rendered)
        self.assertNotIn("Thinking detail hidden", rendered)

    def test_create_result_reminds_pending_external_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = Path(tmpdir) / "agent"
            package_path.mkdir()
            external_config = package_path / "external_config.yaml"
            external_config.write_text("kind: ExternalResourceConfig\n", encoding="utf-8")
            result = CreateAgentResult(
                run_id="run-1",
                requirement="创建墨迹天气 Agent",
                status="completed",
                implemented=True,
                workspace_path=Path(tmpdir) / ".agentfactory",
                trace_path=Path(tmpdir) / ".agentfactory" / "traces" / "factory_runs.jsonl",
                memory_path=Path(tmpdir) / ".agentfactory" / "memory" / "factory_memory.jsonl",
                output_path=package_path,
                pending_configuration_files=[external_config],
                next_steps=[f"Fill runtime external configuration: {external_config}"],
            )
            output = StringIO()
            console = Console(file=output, width=120, force_terminal=False)

            render_create_result(result, console)

            rendered = output.getvalue()
            self.assertIn("Before Real Runtime", rendered)
            self.assertIn("Fill these configuration templates", rendered)
            self.assertIn("external_config.yaml", rendered)

    def test_stream_completion_renders_agent_summary_footer(self) -> None:
        event = FactoryEvent(
            run_id="run-1",
            stage="complete",
            status=EventStatus.COMPLETED,
            title="Factory production completed",
            artifact_path="/tmp/orders-agent",
            payload={
                "verification_status": "passed",
                "tool_test_status": "passed",
                "production_summary": {
                    "status": "completed",
                    "narrative": "订单查询 Agent 已经创建完成，可以通过本地 SQLite 工具查询订单列表和详情。",
                    "capability_summary": "它提供订单列表、详情和搜索能力。",
                    "readiness_summary": "本地验证和工具测试均已通过。",
                    "generated": ["AgentPackage draft created", "3 generated tools"],
                    "satisfied_conditions": ["SQLite schema verified"],
                    "warnings": [],
                    "next_steps": ["/drafts use latest", "/run --input \"列出订单\""],
                },
            },
        )
        output = StringIO()
        console = Console(file=output, width=120, force_terminal=False)

        render_factory_stream_result([event], console)

        rendered = output.getvalue()
        self.assertIn("Created AgentPackage", rendered)
        self.assertIn("订单查询 Agent 已经创建完成", rendered)
        self.assertIn("它提供订单列表、详情和搜索能力", rendered)
        self.assertIn("Generated", rendered)
        self.assertIn("SQLite schema verified", rendered)
        self.assertIn("/run --input", rendered)

    def test_stream_renderer_shows_multi_tool_progress(self) -> None:
        renderer = FactoryStreamRenderer()
        first = FactoryEvent(
            run_id="run-1",
            stage="generate_tool_scripts",
            status=EventStatus.PROGRESS,
            title="Generating tool scripts",
            payload={
                "stream_kind": "node_thinking",
                "tool_id": "list_customer_tickets",
                "tool_index": 1,
                "tool_total": 2,
                "tool_phase": "model_generation_started",
                "flow_summary": "Tool 1/2: list_customer_tickets - calling model for code.",
            },
        )
        second = FactoryEvent(
            run_id="run-1",
            stage="generate_tool_scripts",
            status=EventStatus.PROGRESS,
            title="Generating tool scripts",
            payload={
                "stream_kind": "node_thinking",
                "tool_id": "get_customer_ticket",
                "tool_index": 2,
                "tool_total": 2,
                "tool_phase": "model_generated",
                "flow_summary": "Tool 2/2: get_customer_ticket - model code accepted.",
            },
        )
        output = StringIO()
        console = Console(file=output, width=120, force_terminal=False)

        renderer._record_node_progress(first)
        renderer._record_node_progress(second)
        console.print(renderer._node_panel(second))

        rendered = output.getvalue()
        self.assertIn("Tools", rendered)
        self.assertIn("list_customer_tickets", rendered)
        self.assertIn("get_customer_ticket", rendered)
        self.assertIn("model call started", rendered)
        self.assertIn("model code accepted", rendered)

    def test_render_event_shows_clarification_options(self) -> None:
        event = FactoryEvent(
            run_id="run-1",
            stage="classify_factory_intent",
            status=EventStatus.WARNING,
            title="Factory intent classified",
            message="Create-agent request needs clarification before production.",
            payload={
                "clarification_options": [
                    {
                        "id": "agent_type",
                        "question": "你想创建哪一类 Agent？",
                        "options": [
                            {
                                "id": "customer_service",
                                "label": "客服 Agent",
                                "description": "处理咨询、订单和售后。",
                            }
                        ],
                    }
                ]
            },
        )
        output = StringIO()
        console = Console(file=output, width=120, force_terminal=False)

        render_event(event, console)

        rendered = output.getvalue()
        self.assertIn("你想创建哪一类 Agent", rendered)
        self.assertIn("[customer_service] 客服 Agent", rendered)

    def test_render_event_does_not_duplicate_clarification_question(self) -> None:
        event = FactoryEvent(
            run_id="run-1",
            stage="needs_clarification",
            status=EventStatus.WARNING,
            title="Clarification required",
            message="AgentPackage was not generated.",
            payload={
                "questions": ["你想创建哪一类 Agent？"],
                "clarification_options": [
                    {
                        "id": "agent_type",
                        "question": "你想创建哪一类 Agent？",
                        "options": [{"id": "other", "label": "其他"}],
                    }
                ],
            },
        )
        output = StringIO()
        console = Console(file=output, width=120, force_terminal=False)

        render_event(event, console)

        rendered = output.getvalue()
        self.assertEqual(rendered.count("你想创建哪一类 Agent"), 1)

    def test_shell_clarification_options_always_include_other(self) -> None:
        options = _normalized_question_options(
            {
                "question": "你想管理哪种数据库？",
                "options": [{"id": "sqlite", "label": "SQLite"}],
            }
        )

        self.assertIn("other", {option["id"] for option in options})

    def test_shell_inline_option_label_includes_description(self) -> None:
        label = _inline_option_label(
            {
                "id": "sqlite",
                "label": "SQLite",
                "description": "本地文件数据库。",
            },
            1,
        )

        self.assertEqual(label, "1. SQLite - 本地文件数据库。")

    def test_shell_clarification_answer_accepts_number(self) -> None:
        output = StringIO()
        console = Console(file=output, width=120, force_terminal=False)
        answer = _resolve_clarification_answer(
            "1",
            [
                {"id": "sqlite", "label": "SQLite", "description": ""},
                {"id": "other", "label": "其他", "description": ""},
            ],
            console,
            prompt_session=None,
        )

        self.assertEqual(answer, "SQLite (sqlite)")


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

    def test_slash_create_agent_records_clarification_state(self) -> None:
        result = CreateAgentResult(
            run_id="test-run",
            requirement="创建一个 Agent",
            status="needs_clarification",
            workspace_path=Path.cwd() / ".agentfactory",
            trace_path=Path.cwd() / ".agentfactory" / "traces" / "factory_runs.jsonl",
            memory_path=Path.cwd() / ".agentfactory" / "memory" / "factory_memory.jsonl",
            clarification_questions=["你想创建哪一类 Agent？"],
            clarification_options=[
                {
                    "id": "agent_type",
                    "question": "你想创建哪一类 Agent？",
                    "options": [{"id": "customer_service", "label": "客服 Agent"}],
                }
            ],
        )

        class ClarifyingCreateService:
            def create_agent(self, request: CreateAgentRequest) -> CreateAgentResult:
                return result

        session = ShellSession(pending_requirement="创建一个 Agent")
        dispatcher = SlashCommandDispatcher(
            session=session,
            create_service=ClarifyingCreateService(),
        )

        slash_result = dispatcher.dispatch("/create-agent --draft")

        self.assertEqual(slash_result.kind, "create_agent")
        self.assertEqual(session.pending_clarification_questions, ["你想创建哪一类 Agent？"])
        self.assertEqual(session.pending_clarification_options[0]["id"], "agent_type")

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

    def test_slash_create_agent_accepts_show_thinking_flag(self) -> None:
        service = RecordingCreateAgentService()
        dispatcher = SlashCommandDispatcher(create_service=service)

        result = dispatcher.dispatch('/create-agent --prompt "生成一个客服 Agent" --draft --show-thinking')

        self.assertEqual(result.kind, "create_agent")
        self.assertTrue(service.requests[0].show_thinking)
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
                    run_service=RunAgentService(runtime=_scripted_runtime()),
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
                    run_service=RunAgentService(runtime=_scripted_runtime()),
                )

                result = dispatcher.dispatch('/run --input "你好"')

                self.assertEqual(result.kind, "run_agent")
                self.assertTrue(result.run_result.ok)
                self.assertEqual(result.run_result.package_path, package_path)
            finally:
                os.chdir(cwd)

    def test_slash_run_without_input_enters_agent_chat_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_path = _generated_package(root)
            cwd = Path.cwd()
            os.chdir(root)
            try:
                dispatcher = SlashCommandDispatcher(
                    run_service=RunAgentService(runtime=_scripted_runtime()),
                )

                result = dispatcher.dispatch("/run")

                self.assertEqual(result.kind, "agent_chat")
                self.assertTrue(dispatcher.session.in_agent_chat)
                self.assertEqual(dispatcher.session.active_agent_path, package_path)
                self.assertIn("/clear", result.message or "")
            finally:
                os.chdir(cwd)

    def test_slash_run_with_input_enters_agent_chat_after_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_path = _generated_package(root)
            cwd = Path.cwd()
            os.chdir(root)
            try:
                dispatcher = SlashCommandDispatcher(
                    run_service=RunAgentService(runtime=_scripted_runtime()),
                )

                result = dispatcher.dispatch('/run --input "你好"')

                self.assertEqual(result.kind, "run_agent")
                self.assertTrue(result.run_result.ok)
                self.assertTrue(dispatcher.session.in_agent_chat)
                self.assertEqual(dispatcher.session.active_agent_path, package_path)
            finally:
                os.chdir(cwd)

    def test_process_interrupted_result_is_not_rendered_as_process_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_path = _generated_package(root)
            runtime_result = AgentRunResult(
                run_id="run-interrupted",
                package_path=package_path,
                status="interrupted",
                answer="该操作需要人工确认后才能执行：list_orders。",
                session_id="default",
                tool_results=[
                    ToolResultEnvelope(
                        invocation_id="invocation-1",
                        tool_call_id="call-1",
                        tool_id="list_orders",
                        status="interrupted",
                        observation_summary="Draft generated tool requires approval before execution.",
                        approval_required=True,
                    )
                ],
            )

            class InterruptedProcessManager:
                def run(self, request):
                    return AgentIPCResponse(
                        ok=False,
                        payload=runtime_result.model_dump(mode="json"),
                    )

            with patch(
                "agent_factory.application.run_agent_service.AgentProcessManager",
                return_value=InterruptedProcessManager(),
            ):
                result = RunAgentService().run_agent(
                    RunAgentServiceRequest(
                        target=str(package_path),
                        user_input="列出订单列表",
                    )
                )

            self.assertIsNotNone(result.result)
            self.assertEqual(result.result.status, "interrupted")
            self.assertIsNone(result.error)

            output = StringIO()
            console = Console(file=output, width=120, force_terminal=False)
            render_slash_result(
                SlashCommandResult(kind="run_agent", run_result=result),
                console,
            )
            rendered = output.getvalue()
            self.assertIn("Approval required", rendered)
            self.assertIn("/run --yes", rendered)
            self.assertNotIn("Agent process failed", rendered)

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

    def test_slash_drafts_use_suggests_latest_for_common_typo(self) -> None:
        dispatcher = SlashCommandDispatcher()

        result = dispatcher.dispatch("/drafts use lastest")

        self.assertEqual(result.kind, "error")
        self.assertIn("Did you mean latest", result.message or "")

    def test_contextual_completion_after_drafts_does_not_show_top_level_commands(self) -> None:
        from prompt_toolkit.document import Document

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_path = _generated_package(root)
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
                self.assertFalse(any(str(package_path) == text for text in texts))
                self.assertNotIn("/run", texts)
                self.assertNotIn("/create-agent", texts)
            finally:
                os.chdir(cwd)

    def test_contextual_completion_in_agent_chat_only_shows_chat_commands(self) -> None:
        from prompt_toolkit.document import Document

        session = ShellSession()
        session.enter_agent_chat(target="latest", session_id="default")
        completer = ContextualSlashCompleter(session=session)

        completions = list(completer.get_completions(Document("/"), None))
        texts = [completion.text for completion in completions]

        self.assertEqual(texts, ["/help", "/run --yes", "/exit", "/clear"])

    def test_agent_chat_confirmation_reruns_pending_tool_by_tool_name(self) -> None:
        service = RecordingRunAgentService()
        session = ShellSession()
        session.enter_agent_chat(target="/tmp/example-agent", session_id="default")
        session.capture_tool_approval(
            user_input="江西婺源天气",
            tool_call_id="old-call-id",
            tool_id="weather_query",
        )
        dispatcher = SlashCommandDispatcher(session=session, run_service=service)
        console = Console(file=StringIO(), force_terminal=False)

        handled = _handle_agent_chat_line("确认执行", console, dispatcher)

        self.assertTrue(handled)
        self.assertEqual(len(service.requests), 1)
        self.assertEqual(service.requests[0].user_input, "江西婺源天气")
        self.assertEqual(service.requests[0].approved_tool_call_id, "weather_query")
        self.assertIsNone(session.pending_tool_approval)

    def test_agent_chat_run_yes_approves_pending_tool(self) -> None:
        service = RecordingRunAgentService()
        session = ShellSession()
        session.enter_agent_chat(target="/tmp/example-agent", session_id="default")
        session.capture_tool_approval(
            user_input="江西婺源天气",
            tool_call_id="old-call-id",
            tool_id="weather_query",
        )
        dispatcher = SlashCommandDispatcher(session=session, run_service=service)
        console = Console(file=StringIO(), force_terminal=False)

        handled = _handle_agent_chat_line("/run --yes", console, dispatcher)

        self.assertTrue(handled)
        self.assertEqual(len(service.requests), 1)
        self.assertEqual(service.requests[0].user_input, "江西婺源天气")
        self.assertEqual(service.requests[0].approved_tool_call_id, "weather_query")
        self.assertIsNone(session.pending_tool_approval)

    def test_agent_chat_run_dash_yes_approves_pending_tool(self) -> None:
        service = RecordingRunAgentService()
        session = ShellSession()
        session.enter_agent_chat(target="/tmp/example-agent", session_id="default")
        session.capture_tool_approval(
            user_input="江西婺源天气",
            tool_call_id="old-call-id",
            tool_id="weather_query",
        )
        dispatcher = SlashCommandDispatcher(session=session, run_service=service)
        console = Console(file=StringIO(), force_terminal=False)

        handled = _handle_agent_chat_line("/run -yes", console, dispatcher)

        self.assertTrue(handled)
        self.assertEqual(len(service.requests), 1)
        self.assertEqual(service.requests[0].approved_tool_call_id, "weather_query")
        self.assertIsNone(session.pending_tool_approval)

    def test_drafts_can_resolve_short_display_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package_path = _generated_package(root)
            cwd = Path.cwd()
            os.chdir(root)
            try:
                dispatcher = SlashCommandDispatcher()
                detail = dispatcher.drafts_service.show_draft("latest")
                assert detail is not None

                selected = dispatcher.dispatch(f"/drafts use {detail.summary.display_id}")

                self.assertEqual(selected.kind, "drafts")
                self.assertEqual(dispatcher.session.selected_agent_path, package_path)
            finally:
                os.chdir(cwd)

    def test_slash_exit_requests_exit(self) -> None:
        result = SlashCommandDispatcher().dispatch("/exit")

        self.assertEqual(result.kind, "exit")
        self.assertTrue(result.exit_requested)


if __name__ == "__main__":
    unittest.main()
