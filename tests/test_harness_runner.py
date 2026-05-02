from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.test_factory_agent import service_with_responses, valid_primitives_payload

from agent_factory.application import CreateAgentRequest, CreateAgentService
from agent_factory.harness import AgentHarnessRunner, HarnessLoader, HarnessSpec


class HarnessRunnerTests(unittest.TestCase):
    def test_loader_returns_strong_harness_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))

            spec = HarnessLoader().load(package_path)

            self.assertIsInstance(spec, HarnessSpec)
            self.assertEqual(spec.kind, "HarnessSpec")
            self.assertEqual(len(spec.scenarios), 3)
            self.assertEqual(spec.scenarios[2].expected.selected_tool_id, "order_query")

    def test_runner_executes_each_scenario(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))

            result = AgentHarnessRunner().run(package_path)

            self.assertTrue(result.ok)
            self.assertEqual(result.status, "passed")
            self.assertEqual(result.scenario_count, 3)
            self.assertEqual(result.passed_count, 3)
            self.assertTrue((package_path / "generated" / "reports" / "harness_run.json").exists())

    def test_runner_reports_missing_selected_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            package_path = _generated_package(Path(tmpdir))
            harness_path = package_path / "harness.yaml"
            text = harness_path.read_text(encoding="utf-8")
            harness_path.write_text(
                text.replace("selected_tool: order_query", "selected_tool: missing_tool"),
                encoding="utf-8",
            )

            result = AgentHarnessRunner().run(package_path)

            self.assertFalse(result.ok)
            failed = [
                assertion
                for scenario in result.scenario_results
                for assertion in scenario.assertion_results
                if assertion.status == "failed"
            ]
            self.assertIn("selected_tool_available", {assertion.id for assertion in failed})


def _generated_package(start_path: Path) -> Path:
    service = CreateAgentService(model_service=service_with_responses([valid_primitives_payload()]))
    result = service.create_agent(
        CreateAgentRequest(prompt="创建客服 Agent", start_path=start_path, stream=False)
    )
    assert result.output_path is not None
    return result.output_path


if __name__ == "__main__":
    unittest.main()
