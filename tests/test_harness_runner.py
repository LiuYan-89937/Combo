from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_factory_agent import service_with_responses, valid_primitives_payload

from agent_factory.application import CreateAgentRequest, CreateAgentService
from agent_factory.harness import AgentHarnessRunner, HarnessLoader, HarnessSpec
from agent_factory.runtime import WorkflowRuntime


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
                runtime=WorkflowRuntime(model_service=service_with_responses(["AF-TEST-USER"]))
            )

            result = runner.run(package_path)

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "passed")
            self.assertEqual(result.scenario_count, len(HarnessLoader().load(package_path).scenarios))
            self.assertTrue((package_path / "generated" / "reports" / "harness_run.json").exists())


def _generated_package(start_path: Path) -> Path:
    service = CreateAgentService(model_service=service_with_responses([valid_primitives_payload()]))
    result = service.create_agent(
        CreateAgentRequest(prompt="创建一个通用资料问答 Agent", start_path=start_path, stream=False)
    )
    assert result.output_path is not None
    return result.output_path


if __name__ == "__main__":
    unittest.main()
