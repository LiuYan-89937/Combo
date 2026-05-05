from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ruamel.yaml import YAML

import agent_factory.runtime as runtime_exports
from agent_factory.factory.package_artifacts import PackageArtifactGenerator
from agent_factory.factory.package_writer import PackageWriter
from agent_factory.model import (
    FakeModelAdapter,
    LLMMessage,
    LLMResponse,
    ModelConfig,
    ModelService,
    ToolCallProposal,
)
from agent_factory.runtime import AgentInstanceRuntime, AgentPackageCompiler, AgentRunRequest
from agent_factory.runtime.context_engineering import (
    NodeStateReducer,
    ToolObservationCompressor,
)
from agent_factory.specs import AgentPackagePrimitives
from agent_factory.tools import ToolResultEnvelope
from tests.test_factory_agent import tool_primitives_payload, valid_primitives_payload


class AgentInstanceRuntimeTests(unittest.TestCase):
    def test_legacy_workflow_runtime_is_not_exported(self) -> None:
        self.assertFalse(hasattr(runtime_exports, "WorkflowRuntime"))
        self.assertFalse(hasattr(runtime_exports, "GraphRuntime"))

    def test_generated_runtime_yaml_uses_langgraph_react(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primitives = AgentPackagePrimitives.model_validate(valid_primitives_payload())
            PackageWriter().write_primitives(root, primitives)
            PackageArtifactGenerator().generate_package_specs(root, primitives)

            runtime_yaml = YAML(typ="safe").load((root / "runtime.yaml").read_text(encoding="utf-8"))

            self.assertEqual(runtime_yaml["runtime_type"], "langgraph_react")
            self.assertEqual(runtime_yaml["compile_mode"], "custom_state_graph")

    def test_compiler_returns_langgraph_runtime_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir))
            service = _service_with_responses(["ok"])

            compiled = AgentPackageCompiler().compile(
                package_path,
                model_service=service,
                request=AgentRunRequest(package_path=package_path, user_input="hello"),
            )

            self.assertEqual(compiled.runtime_type, "langgraph_react")
            self.assertIsNotNone(compiled.langgraph_app)
            self.assertGreaterEqual(len(compiled.langchain_tools), 1)

    def test_langgraph_react_runtime_executes_tool_then_observation_then_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir))
            adapter = FakeModelAdapter(
                [
                    LLMResponse(
                        provider="fake",
                        tool_call_proposals=[
                            ToolCallProposal(
                                id="call-001",
                                name="lookup_resource",
                                arguments={"query": "alpha"},
                            )
                        ],
                    ),
                    "工具返回 alpha-result。",
                ]
            )
            service = ModelService.with_adapter(ModelConfig(provider="fake"), adapter)

            result = AgentInstanceRuntime(model_service=service).run(
                AgentRunRequest(package_path=package_path, user_input="查 alpha")
            )

            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.runtime_type, "langgraph_react")
            self.assertEqual(result.answer, "工具返回 alpha-result。")
            self.assertEqual(result.tool_results[0].status, "completed")
            self.assertEqual(result.tool_results[0].output["value"], "alpha-result")
            self.assertEqual(len(adapter.requests), 2)

    def test_langgraph_react_runtime_supports_chained_tool_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir))
            adapter = FakeModelAdapter(
                [
                    LLMResponse(
                        provider="fake",
                        tool_call_proposals=[
                            ToolCallProposal(
                                id="call-001",
                                name="lookup_resource",
                                arguments={"query": "alpha"},
                            )
                        ],
                    ),
                    LLMResponse(
                        provider="fake",
                        tool_call_proposals=[
                            ToolCallProposal(
                                id="call-002",
                                name="lookup_resource",
                                arguments={"query": "beta"},
                            )
                        ],
                    ),
                    "alpha 与 beta 均已处理。",
                ]
            )
            service = ModelService.with_adapter(ModelConfig(provider="fake"), adapter)

            result = AgentInstanceRuntime(model_service=service).run(
                AgentRunRequest(package_path=package_path, user_input="查 alpha 再查 beta")
            )

            self.assertTrue(result.ok, result.error)
            self.assertEqual([item.output["value"] for item in result.tool_results], ["alpha-result", "beta-result"])
            self.assertEqual(len(adapter.requests), 3)

    def test_long_conversation_triggers_context_compression(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir))
            history = [
                LLMMessage(
                    role="user" if index % 2 == 0 else "assistant",
                    content=f"long-history-message-{index}",
                )
                for index in range(30)
            ]
            adapter = FakeModelAdapter(["压缩后的上下文仍可回答。"])
            service = ModelService.with_adapter(ModelConfig(provider="fake"), adapter)

            result = AgentInstanceRuntime(model_service=service).run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input="继续处理",
                    history=history,
                )
            )

            self.assertTrue(result.ok, result.error)
            prompt_messages = adapter.requests[0].messages
            self.assertLess(len(prompt_messages), len(history) + 2)
            self.assertIn("Memory summary", prompt_messages[0].content)

    def test_session_memory_is_reused_by_new_runtime_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir))
            first_adapter = FakeModelAdapter(["first answer"])
            first_service = ModelService.with_adapter(ModelConfig(provider="fake"), first_adapter)

            first = AgentInstanceRuntime(model_service=first_service).run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input="remember this",
                    session_id="shared-session",
                )
            )
            self.assertTrue(first.ok, first.error)

            second_adapter = FakeModelAdapter(["second answer"])
            second_service = ModelService.with_adapter(ModelConfig(provider="fake"), second_adapter)
            second = AgentInstanceRuntime(model_service=second_service).run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input="what changed?",
                    session_id="shared-session",
                )
            )

            self.assertTrue(second.ok, second.error)
            prompt_text = "\n".join(message.content for message in second_adapter.requests[0].messages)
            self.assertIn("remember this", prompt_text)
            self.assertIn("first answer", prompt_text)

    def test_checkpoint_resume_metadata_does_not_leak_secret_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _write_tool_package(Path(tmpdir))
            first_service = _service_with_responses(["first"])

            first = AgentInstanceRuntime(model_service=first_service).run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input="save checkpoint",
                    session_id="checkpoint-session",
                    context={"api_key": "secret-value"},
                )
            )

            self.assertTrue(first.ok, first.error)
            self.assertIsNotNone(first.checkpoint_path)
            checkpoint_text = first.checkpoint_path.read_text(encoding="utf-8")
            self.assertIn("state_hash", checkpoint_text)
            self.assertNotIn("secret-value", checkpoint_text)

            second_service = _service_with_responses(["resumed"])
            second = AgentInstanceRuntime(model_service=second_service).run(
                AgentRunRequest(
                    package_path=package_path,
                    user_input="resume checkpoint",
                    session_id="checkpoint-session",
                    approved_tool_call_id="lookup_resource",
                    context={"api_key": "secret-value"},
                )
            )

            self.assertTrue(second.ok, second.error)
            self.assertTrue(any(event.stage == "checkpoint_resume" for event in second.events))

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


def _write_tool_package(root: Path) -> Path:
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
            "risk_level": "low",
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


def _service_with_responses(responses: list[str | LLMResponse]) -> ModelService:
    return ModelService.with_adapter(ModelConfig(provider="fake"), FakeModelAdapter(responses))


if __name__ == "__main__":
    unittest.main()
