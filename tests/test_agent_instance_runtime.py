from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from ruamel.yaml import YAML

import agent_factory.runtime as runtime_exports
from agent_factory.factory.package_artifacts import PackageArtifactGenerator
from agent_factory.factory.package_writer import PackageWriter
from agent_factory.runtime import AgentInstanceRuntime, AgentRunRequest, RuntimeGraphCompiler
from agent_factory.runtime.context_engineering import (
    NodeStateReducer,
    ToolObservationCompressor,
)
from agent_factory.runtime.langchain_chat import ScriptedRuntimeChatModel
from agent_factory.specs import AgentPackagePrimitives
from agent_factory.tools import ToolResultEnvelope
from tests.test_factory_agent import tool_primitives_payload, valid_primitives_payload


class AgentInstanceRuntimeTests(unittest.TestCase):
    def test_legacy_workflow_runtime_is_not_exported(self) -> None:
        self.assertFalse(hasattr(runtime_exports, "WorkflowRuntime"))
        self.assertFalse(hasattr(runtime_exports, "GraphRuntime"))

    def test_generated_runtime_yaml_uses_langgraph_native_task_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(valid_primitives_payload())
            PackageWriter().write_primitives(root, primitives)
            PackageArtifactGenerator().generate_package_specs(root, primitives)

            runtime_yaml = YAML(typ="safe").load((root / "runtime.yaml").read_text(encoding="utf-8"))

            self.assertEqual(runtime_yaml["runtime_type"], "langgraph_native")
            self.assertEqual(runtime_yaml["compile_mode"], "task_graph")
            self.assertEqual(runtime_yaml["task_graph_file"], "task_graph.yaml")
            self.assertTrue((root / "task_graph.yaml").exists())

    def test_compiler_returns_langgraph_runtime_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir))
            chat_model = ScriptedRuntimeChatModel(responses=["ok"])

            compiled = RuntimeGraphCompiler().compile(
                package_path,
                chat_model=chat_model,
                run_id="test-run",
                session_id="default",
            )

            self.assertEqual(compiled.runtime_type, "langgraph_native")
            self.assertIsNotNone(compiled.langgraph_app)
            self.assertGreaterEqual(len(compiled.langchain_tools), 1)

    def test_langgraph_native_runtime_executes_tool_then_observation_then_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir))
            chat_model = ScriptedRuntimeChatModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call-001",
                                "name": "lookup_resource",
                                "args": {"query": "alpha"},
                            }
                        ],
                    ),
                    "工具返回 alpha-result。",
                ]
            )

            result = AgentInstanceRuntime(chat_model=chat_model).run(
                AgentRunRequest(package_path=package_path, user_input="查 alpha")
            )

            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.runtime_type, "langgraph_native")
            self.assertEqual(result.answer, "工具返回 alpha-result。")
            self.assertEqual(result.tool_results[0].status, "completed")
            self.assertEqual(result.tool_results[0].output["value"], "alpha-result")
            self.assertEqual(len(chat_model.requests), 2)

    def test_langgraph_native_runtime_supports_chained_tool_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir))
            chat_model = ScriptedRuntimeChatModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call-001",
                                "name": "lookup_resource",
                                "args": {"query": "alpha"},
                            }
                        ],
                    ),
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call-002",
                                "name": "lookup_resource",
                                "args": {"query": "beta"},
                            }
                        ],
                    ),
                    "alpha 与 beta 均已处理。",
                ]
            )

            result = AgentInstanceRuntime(chat_model=chat_model).run(
                AgentRunRequest(package_path=package_path, user_input="查 alpha 再查 beta")
            )

            self.assertTrue(result.ok, result.error)
            self.assertEqual([item.output["value"] for item in result.tool_results], ["alpha-result", "beta-result"])
            self.assertEqual(len(chat_model.requests), 3)

    def test_long_conversation_triggers_context_compression(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir))
            history = [
                HumanMessage(content=f"long-history-message-{index}")
                if index % 2 == 0
                else AIMessage(content=f"long-history-message-{index}")
                for index in range(30)
            ]
            chat_model = ScriptedRuntimeChatModel(responses=["压缩后的上下文仍可回答。"])

            result = AgentInstanceRuntime(chat_model=chat_model).run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input="继续处理",
                    history=history,
                )
            )

            self.assertTrue(result.ok, result.error)
            prompt_messages = chat_model.requests[0]
            self.assertLess(len(prompt_messages), len(history) + 2)
            self.assertIn("Memory summary", prompt_messages[0].content)

    def test_session_memory_is_reused_by_new_runtime_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir))
            first_chat_model = ScriptedRuntimeChatModel(responses=["first answer"])

            first = AgentInstanceRuntime(chat_model=first_chat_model).run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input="remember this",
                    session_id="shared-session",
                )
            )
            self.assertTrue(first.ok, first.error)

            second_chat_model = ScriptedRuntimeChatModel(responses=["second answer"])
            second = AgentInstanceRuntime(chat_model=second_chat_model).run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input="what changed?",
                    session_id="shared-session",
                )
            )

            self.assertTrue(second.ok, second.error)
            prompt_text = "\n".join(str(message.content) for message in second_chat_model.requests[0])
            self.assertIn("remember this", prompt_text)
            self.assertIn("first answer", prompt_text)

    def test_approval_resume_uses_checkpointed_tool_call_without_reasking_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir), approval_required=True)
            first_chat_model = ScriptedRuntimeChatModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call-approval",
                                "name": "lookup_resource",
                                "args": {"query": "alpha"},
                            }
                        ],
                    )
                ]
            )

            first = AgentInstanceRuntime(chat_model=first_chat_model).run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input="查 alpha",
                    session_id="approval-session",
                )
            )

            self.assertEqual(first.status, "interrupted")
            self.assertEqual(len(first_chat_model.requests), 1)

            second_chat_model = ScriptedRuntimeChatModel(responses=["已查询 alpha。"])
            second = AgentInstanceRuntime(chat_model=second_chat_model).run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input="查 alpha",
                    session_id="approval-session",
                    approved_tool_call_id="lookup_resource",
                )
            )

            self.assertTrue(second.ok, second.error)
            self.assertEqual(second.tool_results[0].status, "completed")
            self.assertEqual(len(second_chat_model.requests), 1)
            prompt_messages = second_chat_model.requests[0]
            self.assertTrue(any(isinstance(message, AIMessage) and message.tool_calls for message in prompt_messages))
            self.assertTrue(any(message.type == "tool" for message in prompt_messages))

    def test_native_checkpoint_metadata_does_not_leak_secret_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir), approval_required=True)
            first_chat_model = ScriptedRuntimeChatModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "call-secret",
                                "name": "lookup_resource",
                                "args": {"query": "alpha"},
                            }
                        ],
                    )
                ]
            )

            first = AgentInstanceRuntime(chat_model=first_chat_model).run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input="save checkpoint with tool",
                    session_id="checkpoint-session",
                    context={"api_key": "secret-value"},
                )
            )

            self.assertEqual(first.status, "interrupted")
            self.assertIsNotNone(first.checkpoint_path)
            checkpoint_bytes = first.checkpoint_path.read_bytes()
            self.assertNotIn(b"secret-value", checkpoint_bytes)

            second_chat_model = ScriptedRuntimeChatModel(responses=["resumed"])
            second = AgentInstanceRuntime(chat_model=second_chat_model).run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input="resume checkpoint",
                    session_id="checkpoint-session",
                    approved_tool_call_id="lookup_resource",
                    context={"api_key": "secret-value"},
                )
            )

            self.assertTrue(second.ok, second.error)
            self.assertTrue(any(event.stage == "resume" for event in second.events))

    def test_node_state_reducer_blocks_disallowed_fields(self) -> None:
        reducer = NodeStateReducer()

        with self.assertRaises(ValueError):
            reducer.reduce("model_node", {"session_id": "a"}, {"session_id": "b"})

    def test_tool_observation_compressor_redacts_and_truncates(self) -> None:
        envelope = ToolResultEnvelope(
            invocation_id="inv-1",
            tool_call_id="call-1",
            tool_id="lookup_resource",
            status="completed",
            observation_summary="api_key=secret-value " + ("x" * 80),
        )

        compressed = ToolObservationCompressor(max_chars=40).compress(envelope)

        self.assertIn("api_key=[REDACTED]", compressed)
        self.assertIn("[truncated]", compressed)
        self.assertNotIn("secret-value", compressed)


def _write_tool_package(root: Path, *, approval_required: bool = False) -> Path:
    primitives = AgentPackagePrimitives.model_validate(tool_primitives_payload())
    PackageWriter().write_primitives(root, primitives)
    generator = PackageArtifactGenerator()
    generator.generate_package_specs(root, primitives)
    generator.generate_mcp_bindings(root, primitives)
    generator.generate_harness_scenarios(root, primitives)
    tool_dir = root / "generated" / "draft_tools"
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / "lookup_resource.py").write_text(
        "\n".join(
            [
                "def run(input_data, runtime_context):",
                "    query = input_data.get('query', '')",
                "    return {'status': 'completed', 'value': f'{query}-result'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    YAML().dump(
        {
            "schema_version": "0.1",
            "kind": "GeneratedToolDraft",
            "metadata": {
                "name": "lookup_resource",
                "version": "1.0.0",
                "description": "Lookup a controlled resource.",
            },
            "tool_id": "lookup_resource",
            "toolset_id": "generic_tools",
            "source": "factory_generated",
            "status": "available",
            "risk_level": "high" if approval_required else "low",
            "exposure": "exposed",
            "proposal_only": True,
            "selection_strategy": "auto",
            "implementation": {
                "language": "python",
                "path": "generated/draft_tools/lookup_resource.py",
                "entrypoint": "run",
            },
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            "output_schema": {"type": "object"},
            "approval": {"required": False},
        },
        (tool_dir / "lookup_resource.tool.yaml").open("w", encoding="utf-8"),
    )
    report_dir = root / "generated" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "tool_tests.json").write_text(
        '{"status": "passed", "per_tool_status": {"lookup_resource": "passed"}}',
        encoding="utf-8",
    )
    return root


if __name__ == "__main__":
    unittest.main()
