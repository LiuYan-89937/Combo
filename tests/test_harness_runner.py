from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ruamel.yaml import YAML

from tests.test_factory_agent import service_with_responses, valid_primitives_payload

from agent_factory.application import CreateAgentRequest, CreateAgentService
from agent_factory.context import ContextBundle
from agent_factory.harness import AgentHarnessRunner, HarnessLoader, HarnessSpec
from agent_factory.runtime import AgentInstanceRuntime, AgentRunResult, RuntimeEvent
from agent_factory.runtime.langchain_chat import ScriptedRuntimeChatModel


class HarnessRunnerTests(unittest.TestCase):
    def test_loader_returns_strong_harness_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))

            spec = HarnessLoader().load(package_path)

            self.assertIsInstance(spec, HarnessSpec)
            self.assertEqual(spec.kind, "HarnessSpec")
            self.assertGreaterEqual(len(spec.scenarios), 1)
            self.assertEqual(spec.scenarios[0].id, "basic_response_001")

    def test_runner_executes_generic_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            runner = AgentHarnessRunner(
                runtime=AgentInstanceRuntime(chat_model=ScriptedRuntimeChatModel(responses=["AF-TEST-USER"]))
            )

            result = runner.run(package_path)

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "passed")
            self.assertEqual(result.scenario_count, len(HarnessLoader().load(package_path).scenarios))
            self.assertTrue((package_path / "generated" / "reports" / "harness_run.json").exists())

    def test_runner_asserts_context_compression_visibility_and_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            harness_path = package_path / "harness.yaml"
            yaml = YAML()
            data = yaml.load(harness_path.read_text(encoding="utf-8"))
            data.setdefault("fixtures", {})
            data["fixtures"].setdefault("context", {})
            data["fixtures"]["context"] = {
                "api_key": "secret-value",
                "business_id": "tenant-001",
            }
            data["scenarios"] = [
                {
                    "id": "context_runtime_001",
                    "name": "Context compression and visibility",
                    "turns": [{"user": f"turn {index}"} for index in range(13)],
                    "fixtures": ["context:business_id"],
                    "expected": {
                        "context_visibility": {
                            "tool_keys": ["business_id"],
                            "hidden_keys": ["api_key"],
                            "compression_triggered": True,
                            "checkpoint_exists": True,
                        }
                    },
                    "observe": {"context_bundle": True, "memory_ops": True},
                }
            ]
            with harness_path.open("w", encoding="utf-8") as file:
                yaml.dump(data, file)
            runner = AgentHarnessRunner(
                runtime=AgentInstanceRuntime(chat_model=ScriptedRuntimeChatModel(responses=["AF-TEST-USER"]))
            )

            result = runner.run(package_path)

            self.assertTrue(result.ok)
            assertion_statuses = {
                assertion.id: assertion.status
                for assertion in result.scenario_results[0].assertion_results
            }
            self.assertEqual(assertion_statuses["context_tool_keys"], "passed")
            self.assertEqual(assertion_statuses["context_hidden_keys"], "passed")
            self.assertEqual(assertion_statuses["context_compression"], "passed")
            self.assertEqual(assertion_statuses["checkpoint_exists"], "passed")
            report_text = result.report_path.read_text(encoding="utf-8")
            self.assertNotIn("secret-value", report_text)

    def test_runner_can_assert_native_resume_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            harness_path = package_path / "harness.yaml"
            yaml = YAML()
            data = yaml.load(harness_path.read_text(encoding="utf-8"))
            data["scenarios"] = [
                {
                    "id": "native_resume_001",
                    "name": "Native resume assertion",
                    "turns": [{"user": "resume"}],
                    "expected": {
                        "context_visibility": {
                            "native_resume": True,
                            "checkpoint_exists": True,
                        }
                    },
                    "observe": {"trace": True},
                }
            ]
            with harness_path.open("w", encoding="utf-8") as file:
                yaml.dump(data, file)
            runner = AgentHarnessRunner(runtime=_NativeResumeRuntime())

            result = runner.run(package_path)

            self.assertTrue(result.ok)
            assertion_statuses = {
                assertion.id: assertion.status
                for assertion in result.scenario_results[0].assertion_results
            }
            self.assertEqual(assertion_statuses["native_resume"], "passed")
            self.assertEqual(assertion_statuses["checkpoint_exists"], "passed")


def _generated_package(start_path: Path) -> Path:
    service = CreateAgentService(model_service=service_with_responses([valid_primitives_payload()]))
    result = service.create_agent(
        CreateAgentRequest(prompt="创建一个通用资料问答 Agent", start_path=start_path, stream=False)
    )
    assert result.output_path is not None
    return result.output_path


class _NativeResumeRuntime:
    def run(self, request) -> AgentRunResult:
        checkpoint_path = request.package_path / "checkpoints" / "resume-test.json"
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text('{"state_hash": "test"}', encoding="utf-8")
        return AgentRunResult(
            run_id="checkpoint-resume-test",
            package_path=request.package_path,
            status="completed",
            answer="ok",
            session_id=request.session_id,
            checkpoint_path=checkpoint_path,
            context_bundle=ContextBundle(),
            events=[
                RuntimeEvent(
                    run_id="checkpoint-resume-test",
                    stage="resume",
                    status="completed",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
